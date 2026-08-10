/*
 * Recommendation mapping layer -- "Find Your Film".
 *
 * This project's film records (site/assets/films-data.js, built by
 * src/build_recommendation_data.py) only carry real fields: title, director,
 * country, year, runtime, IMDb genres, cluster membership, shared-actor
 * graph degree/neighbors, an englishSpeaking flag derived from country, a
 * real per-film original-language code from TMDB, and outbound links. There
 * is no mood/tone/pace/accessibility field in the dataset, and no plot
 * descriptions or keywords.
 *
 * Everything below is a defensible, hand-authored mapping from the survey's
 * vocabulary onto those real fields -- it never invents genres, countries,
 * or other metadata for a film. Edit the weights here to retune scoring
 * without touching the survey engine (recommendations.js).
 */

// Survey genre option -> real IMDb genre tags present in this collection.
// "documentary" intentionally has no matches: the underlying dataset had its
// documentaries removed before clustering (see methodology.html), so no
// film here carries that tag. "experimental" has no direct IMDb tag either --
// see EXPERIMENTAL_AFFINITY_CLUSTERS below for how that preference is
// approximated instead.
const GENRE_OPTION_TO_IMDB = {
  drama: ["Drama"],
  comedy: ["Comedy"],
  romance: ["Romance"],
  thriller_mystery: ["Thriller", "Mystery", "Film-Noir"],
  crime: ["Crime", "Film-Noir"],
  horror: ["Horror"],
  scifi_fantasy: ["Sci-Fi", "Fantasy"],
  documentary: ["Documentary"],
  war_historical: ["War", "History", "Biography"],
  experimental: [],
};

// Mood (Q1) -> weighted genre affinities. Weights are relative, not a scale
// of any fixed unit -- recommendations.js multiplies them by a shared
// constant.
const MOOD_TO_GENRE_WEIGHTS = {
  comforting: { Comedy: 3, Romance: 2, Family: 2, Musical: 1 },
  exciting: { Action: 3, Adventure: 3, Thriller: 2, "Sci-Fi": 1 },
  emotional: { Drama: 3, Romance: 2, War: 1, Biography: 1 },
  mysterious: { Mystery: 3, Thriller: 2, "Film-Noir": 2, Crime: 1 },
  funny: { Comedy: 3, Musical: 1 },
  challenging: { Drama: 1, Mystery: 1, "Sci-Fi": 1, War: 1 },
  surprise: {},
};

// Moods that read as "push me somewhere unfamiliar" get the same small
// arthouse-cluster nudge as the "experimental" genre and "strange and
// surreal" tone (see EXPERIMENTAL_AFFINITY_CLUSTERS).
const ADVENTUROUS_MOODS = new Set(["challenging", "surprise"]);

// Tone (Q4, up to 2) -> weighted genre affinities.
const TONE_TO_GENRE_WEIGHTS = {
  warm_hopeful: { Comedy: 2, Family: 2, Romance: 2, Music: 1 },
  dark_intense: { Crime: 2, Thriller: 2, "Film-Noir": 2, Horror: 1, War: 1 },
  thoughtful_reflective: { Drama: 3, Biography: 1, History: 1 },
  strange_surreal: { Fantasy: 2, "Sci-Fi": 2 },
  fun_playful: { Comedy: 2, Musical: 2, Adventure: 1 },
  bittersweet: { Drama: 2, Romance: 1, War: 1 },
};

const ADVENTUROUS_TONES = new Set(["strange_surreal"]);

// No IMDb genre tag maps to "experimental" or "avant-garde" in this
// collection. As a defensible fallback we lean on the project's own
// cluster analysis (see BLURBS in src/build_site.py): European Art Cinema
// is explicitly described there as the collection's most heterogeneous,
// arthouse-leaning cluster, so it's the closest real signal available for
// "something formally adventurous." This is a soft nudge, not a filter.
const EXPERIMENTAL_AFFINITY_CLUSTERS = new Set(["european_art_cinema"]);

// Pace (Q3) -> genre lean + runtime lean. Runtime lean is advisory (used
// only to break ties / nudge scoring); the explicit runtime question (Q7)
// is what actually filters.
const PACE_PROFILES = {
  slow_atmospheric: {
    genreWeights: { Drama: 1, Mystery: 1, War: 1 },
    runtimeLean: "long",
  },
  balanced: { genreWeights: {}, runtimeLean: null },
  fast_eventful: {
    genreWeights: { Action: 2, Adventure: 2, Thriller: 1, Comedy: 1 },
    runtimeLean: "short",
  },
  no_preference: { genreWeights: {}, runtimeLean: null },
};

// Era (Q5) -> inclusive [minYear, maxYear] range. null on either end means
// unbounded. "any" carries no range at all (no filter, no bonus).
const ERA_RANGES = {
  pre1950: [null, 1949],
  "1950s_60s": [1950, 1969],
  "1970s_80s": [1970, 1989],
  "1990s_2000s": [1990, 2009],
  "2010s_plus": [2010, null],
  any: null,
};

// Runtime (Q7) -> inclusive [minMinutes, maxMinutes] range.
const RUNTIME_RANGES = {
  under_90: [null, 89],
  "90_120": [90, 120],
  over_120: [121, null],
  no_preference: null,
};

// Language (Q6) -> bonus applied via each film's real `language` field (an
// ISO 639-1 original-language code sourced from TMDB, keyed by imdb_tconst --
// see src/fetch_film_languages.py and build_recommendation_data.py). Soft
// weighting only: "English preferred" merely lowers a non-English film's
// score, it doesn't remove it from consideration.
const LANGUAGE_WEIGHTS = {
  english_preferred: { nonEnglishBonus: -4, englishBonus: 8 },
  no_preference: { nonEnglishBonus: 0, englishBonus: 0 },
};

// When the survey's language dropdown is used to name a specific language,
// this is the bonus for an exact film.language match (and the mild penalty
// for a confirmed non-match -- films with no language data get neither).
const LANGUAGE_MATCH_BONUS = 14;
const LANGUAGE_MISMATCH_PENALTY = -3;

// ISO 639-1 code -> display label, for every original-language value
// present in the current film dataset (see data/film_language.csv) other
// than English, which has its own "English preferred" option. Sorted here
// alphabetically by code; recommendations.js sorts the rendered dropdown by
// label. "cn" is TMDB's own (non-standard) code for Cantonese, kept as TMDB
// returns it rather than remapped to a "correct" ISO code that isn't what
// the data actually says.
const LANGUAGE_LABELS = {
  ar: "Arabic",
  bn: "Bengali",
  cn: "Cantonese",
  cs: "Czech",
  da: "Danish",
  de: "German",
  el: "Greek",
  es: "Spanish",
  fa: "Persian",
  fi: "Finnish",
  fr: "French",
  hu: "Hungarian",
  is: "Icelandic",
  it: "Italian",
  ja: "Japanese",
  kk: "Kazakh",
  ko: "Korean",
  no: "Norwegian",
  pl: "Polish",
  pt: "Portuguese",
  ro: "Romanian",
  ru: "Russian",
  sh: "Serbo-Croatian",
  sv: "Swedish",
  tl: "Tagalog",
  tr: "Turkish",
  wo: "Wolof",
  xx: "No spoken dialogue",
  zh: "Mandarin Chinese",
};

// Adventurousness (Q8) -> how strongly to lean on two real, defensible
// signals: shared-actor graph degree (a proxy for how central/canonical a
// film is to the collection -- see build_recommendation_data.py) and
// whether its cluster is one of the collection's smaller, less-visited
// ones (computed at runtime from the loaded film set, not hardcoded here).
// Each entry is { degreeWeight, nicheWeight, englishBias }.
const ADVENTURE_PROFILES = {
  accessible: { degreeWeight: 8, nicheWeight: -4, englishBias: 3 },
  slightly_outside: { degreeWeight: 1, nicheWeight: 2, englishBias: 0 },
  unusual: { degreeWeight: -3, nicheWeight: 8, englishBias: -2 },
  boldest: { degreeWeight: -5, nicheWeight: 10, englishBias: -4 },
  no_preference: { degreeWeight: 0, nicheWeight: 0, englishBias: 0 },
};

// Countries this collection tags as English-speaking productions (baked
// into each film's englishSpeaking flag already -- kept here only as
// documentation of that heuristic, see build_recommendation_data.py).
const ENGLISH_SPEAKING_COUNTRIES_NOTE =
  "United States, United Kingdom, Canada, Australia, New Zealand, Ireland";
