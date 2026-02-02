"""Shared console and formatting utilities."""

import logging
import os

from rich.console import Console
from rich.logging import RichHandler

# Force colors unless explicitly disabled (NO_COLOR standard)
no_color = os.environ.get("NO_COLOR", "").lower() in ("1", "true", "yes")

console = Console(
    highlight=False,
    force_terminal=not no_color,
    no_color=no_color,
)


def header(title: str) -> None:
    """Print a minimal header."""
    console.print()
    console.print(f"[bold]{title}[/bold]")
    console.print()


def success(msg: str) -> None:
    """Print success message."""
    console.print(f"  [green]✓[/green] {msg}")


def error(msg: str) -> None:
    """Print error message."""
    console.print(f"  [red]✗[/red] {msg}")


def warning(msg: str) -> None:
    """Print warning message."""
    console.print(f"  [yellow]![/yellow] {msg}")


def info(msg: str) -> None:
    """Print info message."""
    console.print(f"  [dim]→[/dim] {msg}")


def dim(msg: str) -> None:
    """Print dimmed text."""
    console.print(f"  [dim]{msg}[/dim]")


def error_panel(msg: str, *, title: str = "Failed") -> None:
    """Print a styled error panel."""
    from rich.box import ROUNDED
    from rich.panel import Panel
    from rich.text import Text

    lines: list[Text] = []
    line = Text()
    line.append("✗ ", style="red bold")
    line.append(title, style="red")
    lines.append(line)
    lines.append(Text())
    lines.append(Text(msg, style="dim"))

    panel = Panel(
        Text("\n").join(lines),
        border_style="red dim",
        box=ROUNDED,
        padding=(0, 1),
        expand=False,
    )
    console.print(panel)


def nl() -> None:
    """Print newline."""
    console.print()


def setup_logging(verbose: bool = False) -> None:
    """Configure clean logging for conduit CLI."""
    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Set up rich handler for clean output
    handler = RichHandler(
        console=console,
        show_time=False,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
        keywords=[],
    )

    # Configure root logger
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[handler],
        force=True,
    )

    # Keep conduit loggers at appropriate level
    logging.getLogger("conduit").setLevel(level)

    # Allow engine worker logs during debugging
    logging.getLogger("conduit.").setLevel(level)
