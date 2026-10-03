"""Figure style for the notebooks, following journal (Nature) figure conventions.

Rules applied to every figure:
- final size in millimeters (width FIGURE_WIDTH_MM); 7 pt text, 6.5 pt ticks and legend,
  8 pt bold panel letters (a, b, c...);
- no axes titles: the figure's claim goes in the legend (the markdown cell below it);
- white background, left and bottom spines only, no grid;
- en-US numbers (decimal point, comma thousands separator) with a typographic minus sign;
- one restrained, fixed palette (COLORS); each entity always has the same color.

Usage:
    viz.setup()
    fig, ax = plt.subplots(figsize=viz.size(height_mm=60), layout="constrained")
    ...
    viz.panel_label(ax, "a")
    viz.save(fig, "fig1_monthly")   # reports/figures/fig1_monthly.{pdf,svg,png}
"""

import re

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.transforms as mtransforms
from matplotlib.colors import LinearSegmentedColormap

from .paths import ROOT

MM = 1 / 25.4                 # inches per millimeter
FIGURE_WIDTH_MM = 160.0       # text width of an A4 page with 3 cm and 2 cm margins
FIGURES_DIR = ROOT / "reports" / "figures"
PNG_DPI = 600
PANEL_LABEL_SIZE = 8          # points
POINTS_PER_INCH = 72

STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "svg.fonttype": "none",   # editable text in SVG
    "pdf.fonttype": 42,       # editable (TrueType) text in PDF
    "font.size": 7,
    "axes.labelsize": 7,
    "axes.titlesize": 7,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.5,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "figure.dpi": 200,        # reasonable on-screen size in the notebook for a 160 mm figure
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.6,
    "axes.grid": False,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "lines.linewidth": 1.0,
    "legend.frameon": False,
    "legend.handlelength": 2.2,
    "figure.constrained_layout.h_pad": 2 / 72,
    "figure.constrained_layout.w_pad": 2 / 72,
}

COLORS = {
    "black": "#272727",
    "grey_mid": "#767676",
    "grey": "#A8A8A8",
    "grey_light": "#D9D9D9",
    "blue": "#0F4D92",
    "blue_mid": "#3775BA",
    "red": "#B64342",
    "red_light": "#DE8B84",
    "teal": "#42949E",
    "brown": "#8C5A2B",
}

# Sequential map for percentages (0 = near white, maximum = dark blue); no rainbow.
SEQUENTIAL = LinearSegmentedColormap.from_list(
    "blue", ["#F4F7FB", "#9DB9DC", COLORS["blue_mid"], COLORS["blue"], "#0A2F5C"])

# ONS curtailment reasons: the color belongs to the reason, not to its position in the chart
REASON_COLORS = {"ENE": COLORS["blue"], "CNF": COLORS["red"], "REL": COLORS["teal"]}
REASON_LABELS = {
    "ENE": "ENE (energy balance)",
    "CNF": "CNF (electrical reliability)",
    "REL": "REL (external unavailability)",
}

# Pairs that appear together in several figures
PLANNED_COLOR = COLORS["grey_mid"]   # ONS day-ahead plan
REALIZED_COLOR = COLORS["blue"]      # recorded curtailment
WEEKDAY_COLOR = COLORS["blue"]
WEEKEND_COLOR = COLORS["red"]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def setup() -> None:
    """Apply the style to every figure created afterwards."""
    mpl.rcParams.update(STYLE)


def size(height_mm: float, width_mm: float = FIGURE_WIDTH_MM) -> tuple[float, float]:
    """Figure size in inches, from millimeters."""
    return width_mm * MM, height_mm * MM


def panel_label(ax, letter: str, dx_pt: float = -24, dy_pt: float = 4) -> None:
    """Bold panel letter (a, b, ...) above and to the left of the y axis."""
    offset = mtransforms.ScaledTranslation(
        dx_pt / POINTS_PER_INCH, dy_pt / POINTS_PER_INCH, ax.figure.dpi_scale_trans)
    ax.text(0.0, 1.0, letter, transform=ax.transAxes + offset, fontsize=PANEL_LABEL_SIZE,
            fontweight="bold", ha="right", va="bottom")


def panel_labels_aligned(fig, axes, letters) -> None:
    """Letters for side-by-side panels at the same height, left of everything each axes draws.

    Use when the y tick labels differ a lot in width (for example, long names) or when a panel is a
    map with a fixed aspect. Call after building the figure and before saving it.
    """
    fig.canvas.draw()
    to_figure = fig.transFigure.inverted()
    renderer = fig.canvas.get_renderer()
    top = max(ax.get_position().y1 for ax in axes)
    gap = 4 / POINTS_PER_INCH / fig.get_figheight()   # 4 pt, as a fraction of the figure height
    for ax, letter in zip(axes, letters):
        left = to_figure.transform(ax.get_tightbbox(renderer).p0)[0]
        fig.text(left, top + gap, letter, fontsize=PANEL_LABEL_SIZE, fontweight="bold",
                 ha="left", va="bottom")


def save(fig, name: str) -> None:
    """Write PDF, SVG (editable text) and a 600 dpi PNG to reports/figures/; show the figure."""
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in (".pdf", ".svg", ".png"):
        fig.savefig(FIGURES_DIR / f"{name}{suffix}", dpi=PNG_DPI if suffix == ".png" else None,
                    bbox_inches="tight", pad_inches=0.02)
    plt.show()


def num(value, decimals: int = 0) -> str:
    """en-US number: decimal point, comma thousands separator and a typographic minus sign (−)."""
    return f"{value:,.{decimals}f}".replace("-", "−")


def comma_axis(axis, decimals: int = 0) -> None:
    """Axis tick labels formatted by num()."""
    axis.set_major_formatter(mticker.FuncFormatter(lambda v, _pos: num(v, decimals)))


def month_axis(ax, dates, every: int = 3) -> None:
    """Categorical month x axis, labeled every `every` months: Apr 2024, Jul 2024, ..."""
    positions = range(len(dates))
    labels = [f"{MONTHS[d.month - 1]} {d:%Y}" for d in dates]
    ax.set_xticks(list(positions)[::every], labels[::every])
    ax.set_xlim(-0.6, len(dates) - 0.4)


_UPPER = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "C"}
_LOWER = {"da", "de", "do", "das", "dos", "e"}


def unit_label(name: str) -> str:
    """Readable cluster name: 'CONJ. FOTOV. ACU III 230KV' -> 'Fotov. Acu III 230 kV'.

    Names are Brazilian proper nouns, so Portuguese connectives (da, de, do...) stay lowercase.
    """
    name = re.sub(r"^conj\.\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(\d+)\s*KV\b", r"\1 kV", name, flags=re.IGNORECASE)
    words = []
    for i, word in enumerate(name.split()):
        if word.upper() in _UPPER:
            words.append(word.upper())
        elif word == "kV":
            words.append(word)
        elif i > 0 and word.lower() in _LOWER:
            words.append(word.lower())
        else:
            words.append(word.capitalize())
    return " ".join(words)
