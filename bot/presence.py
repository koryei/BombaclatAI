"""Controls the bot account's own Discord presence - status, activity, bio.

Every call here is wrapped defensively: presence/profile edits touch
account-level endpoints that can be flakier or more rate-limited than normal
message sends, and a failure here should never take down the rest of the bot.
"""

import logging

import discord

import config

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

_ACTIVITY_TYPE_MAP = {
    "playing": discord.ActivityType.playing,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
    "streaming": discord.ActivityType.streaming,
}


class PresenceManager:
    def __init__(self, client: discord.Client):
        self.client = client

    async def set_status(self, status: str) -> bool:
        resolved = _STATUS_MAP.get(status.lower())
        if resolved is None:
            logger.warning("Unknown status requested: %s", status)
            return False
        try:
            await self.client.change_presence(status=resolved)
            return True
        except Exception:
            logger.exception("Failed to set status to %s", status)
            return False

    @staticmethod
    def _asset_key_for_text(text: str) -> str | None:
        lowered = text.casefold()
        for label, asset_key in config.PRESENCE_ASSET_KEYS.items():
            if label in lowered:
                return asset_key
        return None

    async def set_activity(self, text: str, activity_type: str = "playing") -> bool:
        normalized_type = activity_type.lower()
        resolved_type = _ACTIVITY_TYPE_MAP.get(normalized_type, discord.ActivityType.playing)
        application_id = config.PRESENCE_APPLICATION_ID or None
        asset_key = self._asset_key_for_text(text) if application_id else None
        try:
            activity = discord.Activity(
                name=text[:128],
                type=resolved_type,
                url=config.PRESENCE_STREAM_URL if normalized_type == "streaming" else None,
                application_id=application_id,
                assets={"large_image": asset_key} if asset_key else None,
            )
            await self.client.change_presence(activity=activity)
            return True
        except Exception:
            logger.exception("Failed to set activity to %s", text)
            return False

    async def update_bio(self, text: str) -> bool:
        if self.client.user is None:
            return False
        try:
            await self.client.user.edit(bio=text[:190])
            return True
        except Exception:
            logger.exception("Failed to update bio")
            return False
