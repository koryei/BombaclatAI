import logging

import discord

import config
from bot.autonomous_loop import AutonomousLoop, PresenceLoop
from bot.commands import handle_command
from bot.presence import PresenceManager
from core.brain import Brain
from utils.console_ui import gather_boot_info, render_boot_banner

logger = logging.getLogger(__name__)


class DiscordSelfBotClient(discord.Client):
    def __init__(self, console=None):
        super().__init__()  # type: ignore[call-arg]
        self.console = console
        self.presence_manager = PresenceManager(self)
        self.brain = Brain(self, self.presence_manager)
        self.autonomous_loop = AutonomousLoop(self.brain)
        self.presence_loop = PresenceLoop(self.brain)
        self._banner_printed = False

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)
        if not self.brain.ready:
            await self.brain.start()
            self.autonomous_loop.start()
            self.presence_loop.start()
        await self.brain.announce_restart_if_pending()
        await self.presence_manager.set_status("online")

        if self.console is not None and not self._banner_printed:
            self.console.print(render_boot_banner(gather_boot_info(self)))
            self._banner_printed = True

    async def on_message(self, message: discord.Message) -> None:
        if not self.user:
            return

        is_system = getattr(message, "is_system", False)
        is_system_message = is_system() if callable(is_system) else bool(is_system)
        if is_system_message:
            logger.debug("Ignoring Discord system message %s", getattr(message, "id", "unknown"))
            return

        is_self = message.author.id == self.user.id
        is_command = (
            not is_self
            and message.author.id == config.OWNER_ID
            and message.content.strip().startswith(config.COMMAND_PREFIX)
        )
        await self.brain.ingest_message(
            message,
            is_bot_author=is_self,
            is_command=is_command,
        )

        if is_self:
            return

        try:
            owner_order_reply = await self.brain.handle_owner_order(message)
        except Exception:
            logger.exception("Owner order handling failed in channel %s", message.channel.id)
            owner_order_reply = "i couldn't complete that order and i won't pretend i did"
        if owner_order_reply is not None:
            try:
                sent_confirmation = await message.reply(owner_order_reply[:2000], mention_author=False)
                await self.brain.record_bot_message(
                    message.channel.id,
                    message.guild.id if message.guild else None,
                    owner_order_reply,
                    message_id=getattr(sent_confirmation, "id", None),
                )
            except Exception as exc:
                self.brain.note_discord_delivery_error(exc, "owner action confirmation")
                logger.exception("Failed to confirm owner action in channel %s", message.channel.id)
            return

        if await handle_command(self.brain, message):
            return

        try:
            review_reply = await self.brain.handle_owner_review_message(message)
        except Exception:
            logger.exception("Owner review handling failed in channel %s", message.channel.id)
            review_reply = "i couldn't process that review message safely"
        if review_reply is not None:
            try:
                sent_review_reply = await message.reply(review_reply[:2000], mention_author=False)
                await self.brain.record_review_bot_message(
                    message,
                    review_reply,
                    getattr(sent_review_reply, "id", None),
                )
                await self.brain.record_bot_message(
                    message.channel.id,
                    message.guild.id if message.guild else None,
                    review_reply,
                    message_id=getattr(sent_review_reply, "id", None),
                )
            except Exception as exc:
                self.brain.note_discord_delivery_error(exc, "owner review confirmation")
                logger.exception("Failed to answer owner review in channel %s", message.channel.id)
            return

        # A one-on-one DM is a private conversation - the bot should always
        # be talkative there. A Group DM (a "GC") also has `guild is None`
        # but behaves like a shared channel with multiple people, so it must
        # only get a direct reply on mention; organic engagement in a GC is
        # handled by the autonomous loop instead, same as a server channel.
        is_private_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user in message.mentions
        is_public_vision_request = self.brain.is_explicit_public_vision_request(message)
        is_contextual_vision_follow_up = await self.brain.is_contextual_vision_follow_up(message)
        if not (
            is_private_dm
            or is_mentioned
            or is_public_vision_request
            or is_contextual_vision_follow_up
        ):
            return

        try:
            await self.brain.queue_direct_response(message)
        except Exception:
            logger.exception("Could not queue response batch in channel %s", message.channel.id)

    async def on_reaction_add(self, reaction: discord.Reaction, user) -> None:
        if not self.user or user.id == self.user.id:
            return
        if reaction.message.author.id != self.user.id:
            return
        try:
            await self.brain.handle_reaction(
                reaction.message.id,
                str(reaction.emoji),
                user_id=getattr(user, "id", None),
            )
        except Exception:
            logger.exception("Failed to process reaction feedback")

    async def on_relationship_add(self, relationship) -> None:
        """Pass incoming user-account friend requests to the auto-accept policy."""
        try:
            await self.brain.handle_relationship_add(relationship)
        except Exception:
            logger.exception("Failed to process relationship add")

    async def close(self) -> None:
        self.autonomous_loop.stop()
        self.presence_loop.stop()
        await self.brain.shutdown()
        await super().close()
