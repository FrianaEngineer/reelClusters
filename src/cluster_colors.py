"""Shared cluster -> color mapping, used by hex_viz.py and cluster_graph_viz.py
so the two visualizations always stay in sync."""

# 2026-07-31 Best Picture nominee import: clusters were rebuilt from scratch
# (see src/cluster.py, data/cluster_naming_report.md). Colors for identities
# that survived the rebuild (european_art_cinema, hong_kong_taiwan_cinema,
# czech_new_wave, soviet_cinema, satyajit_ray_indian) are unchanged. Colors
# for identities that evolved (anglophone_classic -> golden_age_hollywood
# _british, japanese_cinema -> classic_japanese_cinema, bergman_scandinavian
# -> scandinavian_bergman_circle) carry over their old hex, since it's the
# same underlying cluster narrower/re-described, not a new one. The two old
# clusters that no longer exist as distinct communities this run
# (transatlantic_auteur_cinema, youssef_chahine_egyptian -- both folded into
# european_art_cinema, see the naming report) freed their colors, reused
# below for the two genuinely new communities (modern_american_cinema,
# silent_era_comedy) rather than inventing an unrelated palette entry.
# japanese_new_wave_genre is a real new split-off with no old color to
# reuse, so it gets a new teal not used elsewhere in this map.
COLOR_MAP = {
    'hiddenGems':                    '#FFFFFF',
    'modern_american_cinema':        '#8D6E63',
    'european_art_cinema':           '#7B1E3A',
    'golden_age_hollywood_british':  '#457B9D',
    'classic_japanese_cinema':       '#1D3557',
    'japanese_new_wave_genre':       '#2A9D8F',
    'hong_kong_taiwan_cinema':       '#E63946',
    'scandinavian_bergman_circle':   '#5E6472',
    'czech_new_wave':                '#B56576',
    'silent_era_comedy':             '#F4A261',
    'soviet_cinema':                 '#9D0208',
    'satyajit_ray_indian':           '#F77F00',
}

# Per-cluster film-node fill colors for the individual cluster network
# visualizations (cluster_ring_viz.py / cluster_graph_viz.py) ONLY -- these
# are deliberately separate from COLOR_MAP above, which stays the source of
# truth for explore.html's hex mosaic (site/hex_grid.svg) and the cluster
# page accent/icon color. Requested by hand (some entries match COLOR_MAP,
# some are a lighter/different shade); "bw" is not derived from "color" via
# darken() here -- both values are fixed as given.
NODE_FILL_MAP = {
    'hiddenGems':                    {'color': '#FFFFFF', 'bw': '#A5A5A5'},
    'modern_american_cinema':        {'color': '#B5A19A', 'bw': '#5B4740'},
    'european_art_cinema':           {'color': '#9c5268', 'bw': '#4F1325'},
    'golden_age_hollywood_british':  {'color': '#93b7cf', 'bw': '#2C4F66'},
    'classic_japanese_cinema':       {'color': '#6a8ab8', 'bw': '#122238'},
    'japanese_new_wave_genre':       {'color': '#6FC2B7', 'bw': '#16554E'},
    'hong_kong_taiwan_cinema':       {'color': '#E63946', 'bw': '#95252D'},
    'scandinavian_bergman_circle':   {'color': '#8a8e99', 'bw': '#3D414A'},
    'czech_new_wave':                {'color': '#B56576', 'bw': '#75414C'},
    # Silent-era comedies are, in practice, all black-and-white (see hex
    # mosaic: every hex in this cluster already renders at the bw shade) --
    # color/bw are set to the same single orangeish tone rather than a
    # bright/dark pair, since there's no "color film" case to contrast against.
    'silent_era_comedy':             {'color': '#9E693F', 'bw': '#9E693F'},
    'soviet_cinema':                 {'color': '#c74c50', 'bw': '#660105'},
    'satyajit_ray_indian':           {'color': '#F77F00', 'bw': '#A05200'},
}


def contrast_text_color(hex_color):
    """Pick black or white text/lines for legibility against a given background."""
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return '#000000' if lum > 0.5 else '#ffffff'
