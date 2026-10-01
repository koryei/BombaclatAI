"""A neofetch/fastfetch-style boot banner plus a live-updating terminal
dashboard, themed around bombaclat's favorite color: green.

Design notes:
- The boot banner is printed once, synchronously, right after login -
  it never needs live data, so it's just a normal `console.print()`.
- The live dashboard only reads cheap, synchronous, in-memory data
  (counters on `BotStats`, the rate limiter's deque length, cached
  discord.py guild/channel objects) so it's safe to re-render several
  times a second from Rich's background refresh thread without touching
  the database or the event loop.
"""

from __future__ import annotations

import platform
import time

import discord
from pyfiglet import Figlet
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

import config

BOMBACLAT_THEME = Theme(
    {
        "brand": "bold green",
        "dim_brand": "green",
        "label": "bold green",
        "value": "white",
        "muted": "grey62",
        "good": "bold green",
        "warn": "yellow",
        "bad": "bold red",
        "logging.level.info": "green",
        "logging.level.warning": "yellow",
        "logging.level.error": "bold red",
        "logging.level.critical": "bold white on red",
    }
)


def create_console() -> Console:
    return Console(theme=BOMBACLAT_THEME)


def _figlet_logo(text: str = "BOMBACLAT") -> Text:
    try:
        rendered = Figlet(font="slant").renderText(text)
    except Exception:
        rendered = text
    return Text(rendered.rstrip("\n"), style="brand")


def render_boot_banner(info: dict[str, str]) -> Panel:
    logo = _figlet_logo()

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="label", justify="right")
    info_table.add_column(style="value")
    for label, value in info.items():
        info_table.add_row(f"{label}", str(value))

    layout = Table.grid(padding=(0, 4))
    layout.add_row(logo, info_table)

    return Panel(
        layout,
        border_style="brand",
        box=box.ROUNDED,
        title="[brand]bombaclat is online[/brand]",
        subtitle="[dim_brand]favorite color: green[/dim_brand]",
        padding=(1, 2),
    )


def gather_boot_info(discord_client: discord.Client) -> dict[str, str]:
    owner = discord_client.get_user(config.OWNER_ID)
    owner_label = f"{owner} ({config.OWNER_ID})" if owner else str(config.OWNER_ID)

    return {
        "account": str(discord_client.user),
        "owner": owner_label,
        "model": config.GEMINI_MODEL,
        "servers": str(len(discord_client.guilds)),
        "command prefix": config.COMMAND_PREFIX,
        "history window": f"{config.HISTORY_SIZE} messages",
        "rate limit": f"{config.RATE_LIMIT_REQUESTS} req / {config.RATE_LIMIT_WINDOW_SECONDS}s",
        "autonomous loop": f"every {config.AUTONOMOUS_LOOP_INTERVAL_SECONDS}s",
        "database": config.DB_PATH,
        "python": platform.python_version(),
        "discord.py-self": discord.__version__,
    }


class Dashboard:
    """A Rich-renderable that pulls a fresh snapshot of bot state every
    time it's rendered, used as the content of a `rich.live.Live`.
    """

    def __init__(self, discord_client: discord.Client, brain) -> None:
        self.discord_client = discord_client
        self.brain = brain

    def __rich__(self) -> Panel:
        stats = self.brain.stats
        client = self.discord_client

        status = "connecting..." if client.user is None else "online"
        if not self.brain.ready:
            status = "starting up..."
        if getattr(self.brain, "captcha_blocked", False):
            status = "CAPTCHA stop"

        used, limit = self.brain.gemini.limiter.current_usage()
        usage_style = "bad" if used >= limit else ("warn" if used >= limit * 0.8 else "good")

        table = Table.grid(padding=(0, 3), expand=True)
        table.add_column(justify="left")
        table.add_column(justify="left")
        table.add_column(justify="left")

        table.add_row(
            _stat("status", status, "good" if status == "online" else "warn"),
            _stat("uptime", stats.uptime_str()),
            _stat("servers", str(len(client.guilds))),
        )
        table.add_row(
            _stat("messages seen", str(stats.messages_seen)),
            _stat("replies sent", str(stats.replies_sent)),
            _stat("api usage", f"{used}/{limit} per min", usage_style),
        )
        table.add_row(
            _stat("autonomous posts", str(stats.autonomous_posts)),
            _stat("autonomous declines", str(stats.autonomous_declines)),
            _stat("reactions sent", str(stats.reactions_sent)),
        )
        table.add_row(
            _stat("memories stored", str(stats.memories_stored)),
            _stat("fallback replies", str(stats.fallback_replies)),
            _stat("gemini errors", str(self.brain.gemini.calls_failed), "bad" if self.brain.gemini.calls_failed else "good"),
        )
        table.add_row(
            _stat("owner dms", str(stats.owner_dms_sent)),
            _stat("reaction failures", str(stats.reaction_failures), "bad" if stats.reaction_failures else "good"),
            _stat("clock", time.strftime("%H:%M:%S")),
        )

        return Panel(
            table,
            title="[brand]live status[/brand]",
            border_style="dim_brand",
            box=box.ROUNDED,
            padding=(1, 2),
        )


def _stat(label: str, value: str, style: str = "value") -> Group:
    text = Text()
    text.append(f"{label}: ", style="label")
    text.append(value, style=style)
    return Group(text)


def render_shutdown_panel() -> Panel:
    return Panel(
        Text(f"bombaclat is offline. logs saved to {config.LOG_PATH}", style="dim_brand", justify="center"),
        border_style="brand",
        box=box.ROUNDED,
    )
