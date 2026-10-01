"""Lightweight, thread-safe-enough counters for the live terminal dashboard.

These are plain in-memory counters, deliberately not backed by the database -
the dashboard reads them synchronously many times a second from the console
UI's refresh thread, so they need to stay cheap and avoid any async/IO calls.
"""

import time
from dataclasses import dataclass, field


@dataclass
class BotStats:
    start_time: float = field(default_factory=time.time)
    messages_seen: int = 0
    replies_sent: int = 0
    autonomous_posts: int = 0
    autonomous_declines: int = 0
    owner_dms_sent: int = 0
    memories_stored: int = 0
    api_calls: int = 0
    api_errors: int = 0
    fallback_replies: int = 0
    reactions_sent: int = 0
    reaction_only_actions: int = 0
    reaction_failures: int = 0
    gifs_sent: int = 0
    gif_classifications: int = 0
    batches_formed: int = 0
    dm_failures: int = 0

    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def uptime_str(self) -> str:
        elapsed = self.uptime_seconds()
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
