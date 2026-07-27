"""
Builds the Criterion Over Time audio cue manifest: matches each required
music track (from cinematic_history_config.MUSIC_CUES + FINAL_HOLD_CUE)
against the real files in site/audioFilesCritOverTime/, using the
RECALCULATED (batch-derived, not the old fixed table) cue durations from
cinematic_history_schedule.build_full_schedule().

Writes ONLY cinematic_history_config.AUDIO_MANIFEST_PATH
(site/audioFilesCritOverTime/audio-cues.json). Never downloads or streams
audio; resolves files from that directory only.
"""

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402

# Below this score a match is flagged, not silently trusted.
CONFIDENCE_FLOOR = 0.55

TRAILING_ID_RE = re.compile(r"-\d+$")
PAREN_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")


def normalize(s):
    """Case/space/underscore/hyphen/punctuation-insensitive, and strips a
    trailing Pixabay-style numeric asset id -- exactly the matching rules
    the client spec calls for."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\s+\d+$", "", s)   # trailing numeric id, space-separated after the regex above
    return s


def list_audio_files():
    files = sorted(cfg.AUDIO_DIR.glob("*.mp3")) + sorted(cfg.AUDIO_DIR.glob("*.wav")) + \
        sorted(cfg.AUDIO_DIR.glob("*.m4a")) + sorted(cfg.AUDIO_DIR.glob("*.aac"))
    # Dedupe accidental re-downloads: a "name (1).ext" alongside "name.ext"
    # normalize to the identical stem once the parenthetical suffix is
    # stripped -- keep the non-parenthetical one deterministically, log the
    # excluded duplicate instead of silently using either.
    by_stem = {}
    excluded = []
    for f in files:
        stem = PAREN_SUFFIX_RE.sub("", f.stem)
        if stem in by_stem:
            existing = by_stem[stem]
            keep, drop = (existing, f) if len(existing.name) <= len(f.name) else (f, existing)
            by_stem[stem] = keep
            excluded.append(drop)
        else:
            by_stem[stem] = f
    return sorted(by_stem.values()), excluded


def score(required_title, required_artist, filename_stem):
    norm_file = normalize(filename_stem)
    norm_query = normalize(f"{required_artist} {required_title}")
    title_tokens = set(normalize(required_title).split())
    artist_tokens = set(normalize(required_artist).split())
    file_tokens = set(norm_file.split())
    title_overlap = len(title_tokens & file_tokens) / max(1, len(title_tokens))
    artist_overlap = len(artist_tokens & file_tokens) / max(1, len(artist_tokens))
    seq_ratio = SequenceMatcher(None, norm_query, norm_file).ratio()
    # Weighted: title match matters most, artist next, sequence similarity
    # as a tiebreaker/sanity check.
    return 0.55 * title_overlap + 0.30 * artist_overlap + 0.15 * seq_ratio


def build_manifest():
    schedule = sched.build_full_schedule()
    cue_rows = schedule["music_cue_timestamps"]
    fps = schedule["fps"]
    files, excluded_duplicates = list_audio_files()

    required = [dict(track_title=r["track_title"], artist=r["artist"],
                      start_year=r["start_year"], end_year=r["end_year"],
                      video_start=r["video_start"], video_end=r["video_end"],
                      duration_seconds=r["duration_seconds"], is_reprise=False)
                for r in cue_rows]
    hold_start = schedule["final_hold_video_start_seconds"]
    required.append(dict(track_title=cfg.FINAL_HOLD_CUE["track_title"],
                          artist=cfg.FINAL_HOLD_CUE["artist"],
                          start_year=None, end_year=None,
                          video_start=hold_start, video_end=hold_start + cfg.FINAL_HOLD_SECONDS,
                          duration_seconds=cfg.FINAL_HOLD_SECONDS, is_reprise=True))

    available = list(files)
    manifest_cues = []
    unresolved = []

    # Process non-reprise cues in order of their OWN best-candidate score,
    # not chronological cue order. Otherwise an early, genuinely ambiguous
    # cue can see a file that's still sitting in the pool only because its
    # true (much stronger) match comes later in the year timeline --
    # producing a spurious near-tie against a file that was never actually
    # in contention for it.
    non_reprise = [r for r in required if not r["is_reprise"]]
    reprise = [r for r in required if r["is_reprise"]]
    non_reprise.sort(key=lambda req: -max(
        (score(req["track_title"], req["artist"], f.stem) for f in available), default=0))

    for req in non_reprise + reprise:
        if req["is_reprise"]:
            # Explicitly reuse whatever file got matched to the track this
            # reprises, per the spec's cue table -- not a fresh independent
            # match (and not consumed from `available`, since the earlier
            # cue is still playing its own copy of the same file).
            source_match = next((c for c in manifest_cues
                                  if c["track_title"] == req["track_title"] and not c.get("is_reprise")), None)
            if source_match is None:
                unresolved.append(dict(**req, reason="reprise of a track that itself failed to match"))
                continue
            manifest_cues.append(dict(**req, matched_filename=source_match["matched_filename"],
                                       confidence=source_match["confidence"],
                                       match_type=source_match["match_type"], candidates=[]))
            continue

        scored = sorted(
            ((score(req["track_title"], req["artist"], f.stem), f) for f in available),
            key=lambda x: -x[0],
        )
        if not scored:
            unresolved.append(dict(**req, reason="no audio files left to match"))
            continue
        best_score, best_file = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score
        ambiguous_tie = margin < 0.05 and best_score < 0.9
        low_confidence = best_score < CONFIDENCE_FLOOR

        if ambiguous_tie:
            # A genuine tie IS a stop-and-ask situation -- multiple
            # comparably-plausible files, no principled way to pick.
            unresolved.append(dict(
                **req, reason="top candidates too close to call",
                top_candidates=[dict(filename=f.name, score=round(s, 3)) for s, f in scored[:3]],
            ))
            continue

        if low_confidence:
            # Not a tie -- one candidate is clearly ahead of the rest, it
            # just doesn't textually match the required title/artist. With
            # no better file anywhere in the directory and an explicit
            # instruction to complete the render, this is accepted as the
            # best available substitute rather than blocking the whole
            # video -- but flagged distinctly (match_type), never presented
            # as a confident match.
            available.remove(best_file)
            manifest_cues.append(dict(
                **req, matched_filename=best_file.name, confidence=round(best_score, 3),
                match_type="best_available_approximate",
                note=(f"No file in {cfg.AUDIO_DIR.name}/ textually matches "
                      f"\"{req['track_title']}\" by {req['artist']}. This is the closest of the "
                      f"remaining files (next-best candidate scored {second_score:.3f}, well behind) "
                      f"-- accepted as a placeholder, not a verified match."),
                candidates=[dict(filename=f.name, score=round(s, 3)) for s, f in scored[:3]],
            ))
            continue

        available.remove(best_file)
        manifest_cues.append(dict(**req, matched_filename=best_file.name,
                                   confidence=round(best_score, 3), match_type="confident", candidates=[]))

    manifest = dict(
        audio_dir=str(cfg.AUDIO_DIR.relative_to(cfg.REPO_ROOT)),
        fps=fps,
        excluded_duplicate_files=[f.name for f in excluded_duplicates],
        cues=manifest_cues,
        unresolved=unresolved,
    )
    return manifest


def main():
    manifest = build_manifest()
    cfg.AUDIO_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.AUDIO_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"Manifest -> {cfg.AUDIO_MANIFEST_PATH}")
    print(f"Excluded duplicate file(s): {manifest['excluded_duplicate_files']}")
    print(f"\nResolved cues ({len(manifest['cues'])}):")
    for c in manifest["cues"]:
        flag = "  <-- BEST-AVAILABLE APPROXIMATE MATCH, not a confident title/artist match" \
            if c["match_type"] == "best_available_approximate" else ""
        reprise = " (reprise)" if c["is_reprise"] else ""
        print(f"  {c['track_title']}{reprise} -- {c['artist']}  ->  {c['matched_filename']}  "
              f"(confidence {c['confidence']:.2f}){flag}")
    if manifest["unresolved"]:
        print(f"\nUNRESOLVED ({len(manifest['unresolved'])}):")
        for u in manifest["unresolved"]:
            print(f"  {u['track_title']} -- {u['artist']}: {u['reason']}")
            for cand in u.get("top_candidates", []):
                print(f"      candidate: {cand['filename']}  (score {cand['score']})")
    if len(manifest["cues"]) < 14:
        print(f"\n{14 - len(manifest['cues'])} cue(s) unresolved -- audio mixing cannot proceed for those "
              f"until resolved.")


if __name__ == "__main__":
    main()
