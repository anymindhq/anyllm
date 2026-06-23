"""ASCII banner for the anyllm CLI.

The art originates from ``docs/ascii.py`` (the "ANSI Shadow" figlet font).
It is embedded here as a clean, importable constant and rendered through Rich
so the same banner can head every entry point of the TUI.
"""
from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.text import Text

from . import __version__

# "ANYLLM" in the ANSI Shadow figlet font (box-drawing glyphs).
BANNER = r"""
 █████╗ ███╗   ██╗██╗   ██╗██╗     ██╗     ███╗   ███╗
██╔══██╗████╗  ██║╚██╗ ██╔╝██║     ██║     ████╗ ████║
███████║██╔██╗ ██║ ╚████╔╝ ██║     ██║     ██╔████╔██║
██╔══██║██║╚██╗██║  ╚██╔╝  ██║     ██║     ██║╚██╔╝██║
██║  ██║██║ ╚████║   ██║   ███████╗███████╗██║ ╚═╝ ██║
╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚══════╝╚═╝     ╚═╝
"""

TAGLINE = "Git for LLM context — snapshot a session, brief the next model."


def render_banner(subtitle: str | None = None) -> Text:
    """Build the styled banner as a Rich ``Text`` object.

    A cyan→blue vertical gradient is applied line by line so the banner reads
    as a single graphic rather than flat text. ``subtitle`` overrides the
    default tagline shown beneath the art.
    """
    lines = [ln for ln in BANNER.splitlines() if ln.strip()]
    # Cool gradient from bright cyan down to blue.
    gradient = ["bright_cyan", "cyan", "cyan", "blue", "blue", "bright_blue"]

    art = Text(justify="left")
    for i, line in enumerate(lines):
        style = gradient[i] if i < len(gradient) else gradient[-1]
        art.append(line + "\n", style=f"bold {style}")

    art.append((subtitle or TAGLINE) + "\n", style="dim italic")
    art.append(f"v{__version__}", style="dim")
    return art


def print_banner(console: Console | None = None, *, subtitle: str | None = None) -> None:
    """Print the centered banner to ``console`` (defaults to a fresh Console)."""
    console = console or Console()
    console.print(Align.left(render_banner(subtitle)))
    console.print()
    console.print()
    console.print()
    console.print()
