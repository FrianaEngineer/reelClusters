"""Shared cluster -> color mapping, used by hex_viz.py and cluster_graph_viz.py
so the two visualizations always stay in sync."""

COLOR_MAP = {
    'hiddenGems':               '#FFFFFF',
    'european_art_cinema':      '#7B1E3A',
    'japanese_cinema':          '#1D3557',
    'anglophone_classic':       '#457B9D',
    'transatlantic_auteur_cinema': '#F4A261',
    'hong_kong_taiwan_cinema':  '#E63946',
    'bergman_scandinavian':     '#5E6472',
    'czech_new_wave':           '#B56576',
    'soviet_cinema':            '#9D0208',
    'satyajit_ray_indian':      '#F77F00',
    'youssef_chahine_egyptian': '#8D6E63',
}

# Per-cluster film-node fill colors for the individual cluster network
# visualizations (cluster_ring_viz.py / cluster_graph_viz.py) ONLY -- these
# are deliberately separate from COLOR_MAP above, which stays the source of
# truth for explore.html's hex mosaic (site/hex_grid.svg) and the cluster
# page accent/icon color. Requested by hand (some entries match COLOR_MAP,
# some are a lighter/different shade); "bw" is not derived from "color" via
# darken() here -- both values are fixed as given.
NODE_FILL_MAP = {
    'hiddenGems':                  {'color': '#FFFFFF', 'bw': '#A5A5A5'},
    'european_art_cinema':         {'color': '#9c5268', 'bw': '#4F1325'},
    'japanese_cinema':             {'color': '#6a8ab8', 'bw': '#122238'},
    'anglophone_classic':          {'color': '#93b7cf', 'bw': '#2C4F66'},
    'transatlantic_auteur_cinema': {'color': '#F4A261', 'bw': '#9E693F'},
    'hong_kong_taiwan_cinema':     {'color': '#E63946', 'bw': '#95252D'},
    'bergman_scandinavian':        {'color': '#8a8e99', 'bw': '#3D414A'},
    'czech_new_wave':              {'color': '#B56576', 'bw': '#75414C'},
    'soviet_cinema':               {'color': '#c74c50', 'bw': '#660105'},
    'satyajit_ray_indian':         {'color': '#F77F00', 'bw': '#A05200'},
    'youssef_chahine_egyptian':    {'color': '#8D6E63', 'bw': '#5B4740'},
}


def contrast_text_color(hex_color):
    """Pick black or white text/lines for legibility against a given background."""
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return '#000000' if lum > 0.5 else '#ffffff'
