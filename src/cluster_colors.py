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


def contrast_text_color(hex_color):
    """Pick black or white text/lines for legibility against a given background."""
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return '#000000' if lum > 0.5 else '#ffffff'
