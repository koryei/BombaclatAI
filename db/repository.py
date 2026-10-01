import json
import re
import time
from typing import Optional

import config
from core.gif_library import source_key
from core.models import MemoryCandidate, MessageRecord, UserVibe
from db.database import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- messages
    async def add_message(
        self,
        *,
        guild_id: Optional[int],
        channel_id: int,
        user_id: int,
        author_name: str,
        content: str,
        is_bot: bool = False,
        is_dm: bool = False,
        timestamp: Optional[float] = None,
        message_id: Optional[int] = None,
        is_command: bool = False,
        is_attachment_only: bool = False,
    ) -> None:
        await self.db.execute(
            """INSERT OR IGNORE INTO messages
               (timestamp, guild_id, channel_id, user_id, author_name, content,
                is_bot, is_dm, discord_message_id, is_command, is_attachment_only)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp or time.time(),
                guild_id,
                channel_id,
                user_id,
                author_name,
                content,
                int(is_bot),
                int(is_dm),
                message_id,
                int(is_command),
                int(is_attachment_only),
            ),
        )

    async def get_recent_messages(self, channel_id: int, limit: int = 20) -> list[MessageRecord]:
        rows = await self.db.fetchall(
            """SELECT * FROM messages
               WHERE channel_id = ? AND is_command = 0
               ORDER BY timestamp DESC LIMIT ?""",
            (channel_id, limit),
        )
        records = [
            MessageRecord(
                user_id=row["user_id"],
                author_name=row["author_name"],
                content=row["content"],
                timestamp=row["timestamp"],
                is_bot=bool(row["is_bot"]),
                guild_id=row["guild_id"],
                channel_id=row["channel_id"],
                message_id=row["discord_message_id"],
                is_command=bool(row["is_command"]),
                is_attachment_only=bool(row["is_attachment_only"]),
            )
            for row in rows
        ]
        records.reverse()  # oldest -> newest
        return records

    async def get_messages_before(
        self,
        channel_id: int,
        timestamp: float,
        limit: int = 8,
    ) -> list[MessageRecord]:
        rows = await self.db.fetchall(
            """SELECT * FROM messages
               WHERE channel_id = ? AND timestamp <= ? AND is_command = 0
               ORDER BY timestamp DESC LIMIT ?""",
            (channel_id, timestamp, max(1, min(limit, 30))),
        )
        records = [
            MessageRecord(
                user_id=row["user_id"],
                author_name=row["author_name"],
                content=row["content"],
                timestamp=row["timestamp"],
                is_bot=bool(row["is_bot"]),
                guild_id=row["guild_id"],
                channel_id=row["channel_id"],
                message_id=row["discord_message_id"],
                is_command=bool(row["is_command"]),
                is_attachment_only=bool(row["is_attachment_only"]),
            )
            for row in rows
        ]
        records.reverse()
        return records

    async def get_message_by_discord_id(self, message_id: int) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM messages WHERE discord_message_id = ? LIMIT 1",
            (message_id,),
        )
        return dict(row) if row else None

    async def get_active_channels(self, since_seconds: float = 600) -> list[tuple[int, Optional[int]]]:
        """Channels with any activity in the last `since_seconds`, for the autonomous loop."""
        cutoff = time.time() - since_seconds
        rows = await self.db.fetchall(
            """SELECT DISTINCT channel_id, guild_id FROM messages
               WHERE timestamp >= ? AND is_bot = 0 AND is_command = 0""",
            (cutoff,),
        )
        return [(row["channel_id"], row["guild_id"]) for row in rows]

    async def find_user_by_name(self, reference: str) -> Optional[dict]:
        normalized = reference.strip().casefold()
        row = await self.db.fetchone(
            """SELECT user_id, username FROM users
               WHERE lower(username) = ? OR lower(username) LIKE ?
               ORDER BY CASE WHEN lower(username) = ? THEN 0 ELSE 1 END,
                        last_seen DESC LIMIT 1""",
            (normalized, f"{normalized}%", normalized),
        )
        return dict(row) if row else None

    async def find_shared_channel(
        self,
        first_user_id: int,
        second_user_id: int,
        since_seconds: float = 30 * 86400,
    ) -> Optional[dict]:
        """Find the most recently active non-private channel where both users spoke."""
        cutoff = time.time() - since_seconds
        row = await self.db.fetchone(
            """SELECT m.channel_id, m.guild_id, MAX(m.timestamp) AS last_seen
               FROM messages m
               JOIN channel_settings cs ON cs.channel_id = m.channel_id
               WHERE m.timestamp >= ?
                 AND m.is_bot = 0
                 AND m.is_command = 0
                 AND cs.is_private_dm = 0
                 AND m.user_id IN (?, ?)
               GROUP BY m.channel_id, m.guild_id
               HAVING COUNT(DISTINCT m.user_id) = 2
               ORDER BY last_seen DESC LIMIT 1""",
            (cutoff, first_user_id, second_user_id),
        )
        return dict(row) if row else None

    async def prune_old_messages(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        await self.db.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))

    # -------------------------------------------------------------------- users
    async def get_user(self, user_id: int) -> Optional[UserVibe]:
        row = await self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not row:
            return None
        return UserVibe(
            user_id=row["user_id"],
            energy=row["vibe_energy"],
            formality=row["vibe_formality"],
            trust_score=row["trust_score"],
            interaction_count=row["interaction_count"],
            message_count=row["message_count"] or 0,
            question_count=row["question_count"] or 0,
            emoji_count=row["emoji_count"] or 0,
        )

    async def upsert_user_seen(
        self,
        user_id: int,
        username: str,
        is_owner: bool,
        *,
        count_interaction: bool = True,
    ) -> None:
        now = time.time()
        increment = int(count_interaction)
        await self.db.execute(
            """INSERT INTO users
               (user_id, username, is_owner, first_seen, last_seen, interaction_count)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   last_seen = excluded.last_seen,
                   is_owner = excluded.is_owner,
                   interaction_count = users.interaction_count + excluded.interaction_count""",
            (user_id, username, int(is_owner), now, now, increment),
        )

    async def record_user_message_style(self, user_id: int, content: str) -> None:
        """Persist lightweight, non-sensitive communication signals for a user."""
        if not content or not content.strip():
            return
        question = int("?" in content)
        emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF]", content))
        await self.db.execute(
            """UPDATE users SET message_count = message_count + 1,
                   question_count = question_count + ?,
                   emoji_count = emoji_count + ?
               WHERE user_id = ?""",
            (question, emoji_count, user_id),
        )

    async def update_user_vibe(self, user_id: int, energy: float, formality: float) -> None:
        await self.db.execute(
            "UPDATE users SET vibe_energy = ?, vibe_formality = ? WHERE user_id = ?",
            (energy, formality, user_id),
        )

    async def adjust_trust(self, user_id: int, delta: float) -> None:
        await self.db.execute(
            "UPDATE users SET trust_score = MAX(0.0, MIN(1.0, trust_score + ?)) WHERE user_id = ?",
            (delta, user_id),
        )

    # ----------------------------------------------------------------- memories
    async def add_memory(self, memory: MemoryCandidate) -> None:
        await self.db.execute(
            """INSERT INTO memories
               (created_at, about_user_id, memory_text, category, confidence, guild_id,
                is_sensitive, verified_by_owner, source_channel_id, source_is_private_dm, source_message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                memory.about_user_id,
                memory.memory_text,
                memory.category,
                memory.confidence,
                memory.guild_id,
                int(memory.is_sensitive),
                int(memory.verified_by_owner),
                memory.source_channel_id,
                int(memory.source_is_private_dm),
                memory.source_message_id,
            ),
        )

    async def get_memories_for_user(self, user_id: int, limit: int = 5) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT * FROM memories WHERE about_user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def get_context_memories(
        self,
        user_id: int,
        *,
        is_private_dm: bool,
        channel_id: Optional[int],
        limit: int = 5,
    ) -> list[dict]:
        """Return memories safe for this exact conversation context.

        Non-sensitive memories can travel with the user's profile. Sensitive
        memories are restricted to the same private DM channel that created
        them, so a fact from a private conversation cannot leak into a GC.
        """
        rows = await self.db.fetchall(
            """SELECT * FROM memories
               WHERE about_user_id = ?
                 AND (
                   is_sensitive = 0
                   OR (? = 1 AND source_is_private_dm = 1 AND source_channel_id = ?)
                 )
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, int(is_private_dm), channel_id, limit),
        )
        return [dict(row) for row in rows]

    async def list_memories(self, user_id: Optional[int] = None, limit: int = 20) -> list[dict]:
        if user_id is not None:
            rows = await self.db.fetchall(
                "SELECT * FROM memories WHERE about_user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [dict(row) for row in rows]

    async def delete_memory(self, memory_id: int) -> None:
        await self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    async def prune_old_memories(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        await self.db.execute("DELETE FROM memories WHERE created_at < ?", (cutoff,))

    async def prune_old_events(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        await self.db.execute("DELETE FROM interaction_events WHERE timestamp < ?", (cutoff,))

    async def list_memories_with_usernames(self, limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT m.*, u.username FROM memories m
               LEFT JOIN users u ON u.user_id = m.about_user_id
               ORDER BY m.created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in rows]

    async def is_duplicate_memory(self, user_id: int, memory_text: str) -> bool:
        row = await self.db.fetchone(
            """SELECT id FROM memories
               WHERE about_user_id = ? AND lower(trim(memory_text)) = lower(trim(?))
               LIMIT 1""",
            (user_id, memory_text),
        )
        return row is not None

    # ---------------------------------------------------------------- decisions
    async def log_decision(
        self,
        *,
        guild_id: Optional[int],
        channel_id: int,
        trigger_type: Optional[str],
        decision: str,
        reasoning: str,
        confidence: float,
        message_sent: Optional[str] = None,
        action_type: str = "text",
        reaction_emoji: Optional[str] = None,
        gif_category: Optional[str] = None,
        target_message_id: Optional[int] = None,
    ) -> int:
        return await self.db.execute(
            """INSERT INTO decisions
               (timestamp, guild_id, channel_id, trigger_type, decision, reasoning, confidence,
               message_sent, action_type, reaction_emoji, gif_category, target_message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), guild_id, channel_id, trigger_type, decision, reasoning,
                confidence, message_sent, action_type, reaction_emoji, gif_category, target_message_id,
            ),
        )

    async def get_decision(self, decision_id: int) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM decisions WHERE id = ?", (decision_id,))
        return dict(row) if row else None

    async def update_decision_feedback(self, decision_id: int, feedback: str) -> None:
        await self.db.execute(
            "UPDATE decisions SET owner_feedback = ?, feedback_timestamp = ? WHERE id = ?",
            (feedback, time.time(), decision_id),
        )

    async def mark_dm_sent(self, decision_id: int) -> None:
        await self.db.execute("UPDATE decisions SET dm_sent = 1 WHERE id = ?", (decision_id,))

    async def set_sent_message_id(self, decision_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE decisions SET sent_message_id = ? WHERE id = ?", (message_id, decision_id)
        )

    async def set_reaction_target(self, decision_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE decisions SET target_message_id = ? WHERE id = ?", (message_id, decision_id)
        )

    async def get_decision_by_message_id(self, message_id: int) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM decisions WHERE sent_message_id = ?", (message_id,)
        )
        return dict(row) if row else None

    async def set_message_sent(self, decision_id: int, message_sent: str) -> None:
        await self.db.execute(
            "UPDATE decisions SET message_sent = ? WHERE id = ?", (message_sent, decision_id)
        )

    async def get_recent_decisions(self, limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- GIF library
    async def get_gif(self, url: str) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM gif_library WHERE url = ?", (url,))
        if row:
            return dict(row)

        # Discord attachment URLs carry rotating signed query parameters. A
        # new history fetch can therefore produce a different URL for the
        # same underlying GIF; compare stable host/path identities too.
        key = source_key(url)
        rows = await self.db.fetchall("SELECT * FROM gif_library WHERE enabled = 1")
        for candidate in rows:
            if source_key(candidate["url"]) == key:
                return dict(candidate)
        return None

    async def upsert_gif(
        self,
        *,
        url: str,
        source_channel_id: Optional[int],
        source_message_id: Optional[int],
        mime_type: str,
        categories: list[str],
        description: str,
        confidence: float,
    ) -> int:
        existing = await self.get_gif(url)
        encoded_categories = json.dumps(categories[:3], ensure_ascii=False)
        if existing:
            await self.db.execute(
                """UPDATE gif_library SET source_channel_id = ?, source_message_id = ?,
                   url = ?, mime_type = ?, categories = ?, description = ?, confidence = ?, enabled = 1
                   WHERE id = ?""",
                (
                    source_channel_id,
                    source_message_id,
                    url,
                    mime_type,
                    encoded_categories,
                    description[:240],
                    max(0.0, min(float(confidence), 1.0)),
                    existing["id"],
                ),
            )
            return int(existing["id"])
        return await self.db.execute(
            """INSERT INTO gif_library
               (url, source_channel_id, source_message_id, mime_type, categories,
                description, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url,
                source_channel_id,
                source_message_id,
                mime_type,
                encoded_categories,
                description[:240],
                max(0.0, min(float(confidence), 1.0)),
                time.time(),
            ),
        )

    async def list_gifs(self, limit: int = 200) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM gif_library WHERE enabled = 1 ORDER BY created_at ASC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        return [dict(row) for row in rows]

    async def mark_gif_used(self, gif_id: int) -> None:
        await self.db.execute(
            """UPDATE gif_library SET last_used = ?, use_count = use_count + 1
               WHERE id = ?""",
            (time.time(), gif_id),
        )

    # --------------------------------------------------------- humor feedback
    async def record_humor_feedback(
        self,
        *,
        channel_id: int,
        target_message_id: int,
        reviewer_id: int,
        label: str,
        note: str,
        response_text: str,
        context_json: str,
    ) -> bool:
        inserted = await self.db.execute_count(
            """INSERT OR IGNORE INTO humor_feedback
               (created_at, channel_id, target_message_id, reviewer_id, label, note,
                response_text, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                channel_id,
                target_message_id,
                reviewer_id,
                label,
                note[:300],
                response_text[:2000],
                context_json[:12000],
            ),
        )
        return inserted > 0

    async def list_humor_feedback(self, label: str, limit: int = 6) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT * FROM humor_feedback
               WHERE label = ?
               ORDER BY created_at DESC LIMIT ?""",
            (label, max(1, min(limit, 20))),
        )
        return [dict(row) for row in rows]

    async def count_humor_feedback(self) -> dict[str, int]:
        rows = await self.db.fetchall(
            "SELECT label, COUNT(*) AS count FROM humor_feedback GROUP BY label"
        )
        counts = {"good": 0, "bad": 0}
        for row in rows:
            if row["label"] in counts:
                counts[row["label"]] = int(row["count"])
        return counts

    # ------------------------------------------------------------- owner reviews
    async def create_review_session(
        self,
        *,
        decision_id: int,
        expires_at: float,
        owner_id: int,
        guild_id: Optional[int],
        channel_id: Optional[int],
        is_private_channel: bool,
        mode: str,
        context_json: str,
        report_text: str,
        status: str = "pending",
    ) -> int:
        await self.db.execute(
            """INSERT OR IGNORE INTO review_sessions
               (decision_id, created_at, expires_at, owner_id, guild_id, channel_id,
                is_private_channel, status, mode, context_json, report_text, last_interaction_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                time.time(),
                expires_at,
                owner_id,
                guild_id,
                channel_id,
                int(is_private_channel),
                status,
                mode,
                context_json,
                report_text,
                time.time(),
            ),
        )
        row = await self.db.fetchone(
            "SELECT id FROM review_sessions WHERE decision_id = ?", (decision_id,)
        )
        return int(row["id"]) if row else 0

    async def get_review_session(self, session_id: int) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM review_sessions WHERE id = ?", (session_id,))
        return dict(row) if row else None

    async def get_review_session_by_decision(self, decision_id: int) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM review_sessions WHERE decision_id = ?", (decision_id,)
        )
        return dict(row) if row else None

    async def get_review_session_by_message(self, message_id: int) -> Optional[dict]:
        row = await self.db.fetchone(
            """SELECT s.* FROM review_sessions s
               LEFT JOIN review_messages m ON m.session_id = s.id
               WHERE s.review_message_id = ? OR m.discord_message_id = ?
               ORDER BY s.id DESC LIMIT 1""",
            (message_id, message_id),
        )
        return dict(row) if row else None

    async def list_review_sessions(
        self,
        *,
        statuses: tuple[str, ...] = ("pending", "delivered", "awaiting_approval"),
        limit: int = 10,
    ) -> list[dict]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = await self.db.fetchall(
            f"""SELECT * FROM review_sessions
                WHERE status IN ({placeholders}) AND expires_at > ?
                ORDER BY created_at DESC LIMIT ?""",
            (*statuses, time.time(), limit),
        )
        return [dict(row) for row in rows]

    async def count_review_sessions(self, statuses: tuple[str, ...] = ("pending",)) -> int:
        placeholders = ", ".join("?" for _ in statuses)
        row = await self.db.fetchone(
            f"SELECT COUNT(*) AS count FROM review_sessions WHERE status IN ({placeholders}) AND expires_at > ?",
            (*statuses, time.time()),
        )
        return int(row["count"] if row else 0)

    async def mark_review_delivered(
        self,
        session_id: int,
        review_channel_id: int,
        review_message_id: int,
    ) -> None:
        now = time.time()
        await self.db.execute(
            """UPDATE review_sessions
               SET status = CASE WHEN status = 'awaiting_approval' THEN status ELSE 'delivered' END,
                   review_channel_id = ?, review_message_id = ?, delivered_at = ?,
                   last_interaction_at = ?
               WHERE id = ?""",
            (review_channel_id, review_message_id, now, now, session_id),
        )

    async def update_review_report(self, session_id: int, report_text: str) -> None:
        await self.db.execute(
            "UPDATE review_sessions SET report_text = ?, last_interaction_at = ? WHERE id = ?",
            (report_text, time.time(), session_id),
        )

    async def set_review_status(self, session_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE review_sessions SET status = ?, last_interaction_at = ? WHERE id = ?",
            (status, time.time(), session_id),
        )

    async def record_review_feedback(
        self,
        session_id: int,
        feedback: str,
        note: str,
        source: str,
    ) -> bool:
        now = time.time()
        changed = await self.db.execute_count(
            """UPDATE review_sessions
               SET feedback = ?, feedback_note = ?, feedback_source = ?, feedback_at = ?,
                   status = CASE WHEN status = 'awaiting_approval' THEN status ELSE 'reviewed' END,
                   last_interaction_at = ?
               WHERE id = ? AND (feedback IS NULL OR feedback = '')""",
            (feedback, note, source, now, now, session_id),
        )
        return changed > 0

    async def add_review_message(
        self,
        session_id: int,
        author_id: int,
        direction: str,
        content: str,
        discord_message_id: Optional[int] = None,
    ) -> int:
        message_id = await self.db.execute(
            """INSERT INTO review_messages
               (session_id, timestamp, author_id, direction, content, discord_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, time.time(), author_id, direction, content, discord_message_id),
        )
        await self.db.execute(
            "UPDATE review_sessions SET last_interaction_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        return message_id

    async def get_review_messages(self, session_id: int, limit: int = 20) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT * FROM review_messages WHERE session_id = ?
               ORDER BY timestamp ASC LIMIT ?""",
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    async def prune_review_sessions(self, retention_days: int) -> None:
        now = time.time()
        await self.db.execute(
            """UPDATE review_sessions SET status = 'expired', last_interaction_at = ?
               WHERE expires_at <= ? AND status IN ('pending', 'delivered', 'awaiting_approval')""",
            (now, now),
        )
        cutoff = now - retention_days * 86400
        await self.db.execute("DELETE FROM review_messages WHERE timestamp < ?", (cutoff,))

    # ---------------------------------------------------------- trigger weights
    async def get_trigger_weight(self, trigger_type: str) -> float:
        row = await self.db.fetchone(
            "SELECT weight FROM trigger_weights WHERE trigger_type = ?", (trigger_type,)
        )
        return row["weight"] if row else 1.0

    async def get_all_trigger_weights(self) -> list[dict]:
        rows = await self.db.fetchall("SELECT * FROM trigger_weights ORDER BY trigger_type")
        return [dict(row) for row in rows]

    async def set_trigger_weight(
        self, trigger_type: str, weight: float, success_count: int, failure_count: int
    ) -> None:
        existing = await self.db.fetchone(
            "SELECT trigger_type FROM trigger_weights WHERE trigger_type = ?", (trigger_type,)
        )
        if existing:
            await self.db.execute(
                """UPDATE trigger_weights SET weight = ?, success_count = ?,
                   failure_count = ?, last_updated = ? WHERE trigger_type = ?""",
                (weight, success_count, failure_count, time.time(), trigger_type),
            )
        else:
            await self.db.execute(
                """INSERT INTO trigger_weights
                   (trigger_type, weight, success_count, failure_count, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (trigger_type, weight, success_count, failure_count, time.time()),
            )

    # ------------------------------------------------------------------ config
    async def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = await self.db.fetchone("SELECT value FROM bot_config WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_config(self, key: str, value: str) -> None:
        existing = await self.db.fetchone("SELECT key FROM bot_config WHERE key = ?", (key,))
        if existing:
            await self.db.execute(
                "UPDATE bot_config SET value = ?, updated_at = ? WHERE key = ?",
                (value, time.time(), key),
            )
        else:
            await self.db.execute(
                "INSERT INTO bot_config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, time.time()),
            )

    async def get_all_config(self) -> dict:
        rows = await self.db.fetchall("SELECT key, value FROM bot_config")
        return {row["key"]: row["value"] for row in rows}

    # --------------------------------------------------------------- reminders
    async def create_reminder(
        self,
        *,
        user_id: int,
        channel_id: int,
        guild_id: Optional[int],
        text: str,
        due_at: float,
    ) -> int:
        return await self.db.execute(
            """INSERT INTO reminders
               (user_id, channel_id, guild_id, text, due_at, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (user_id, channel_id, guild_id, text, due_at, time.time()),
        )

    async def get_due_reminders(self, now: Optional[float] = None, limit: int = 20) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT * FROM reminders
               WHERE status = 'pending' AND due_at <= ?
               ORDER BY due_at ASC LIMIT ?""",
            (now if now is not None else time.time(), limit),
        )
        return [dict(row) for row in rows]

    async def mark_reminder_delivered(self, reminder_id: int, message_id: Optional[int]) -> None:
        await self.db.execute(
            """UPDATE reminders
               SET status = 'delivered', delivered_at = ?, discord_message_id = ?
               WHERE id = ? AND status = 'pending'""",
            (time.time(), message_id, reminder_id),
        )

    async def cancel_reminder(
        self,
        reminder_id: int,
        requester_id: int,
        *,
        channel_id: Optional[int] = None,
    ) -> bool:
        row = await self.db.fetchone("SELECT user_id, channel_id, status FROM reminders WHERE id = ?", (reminder_id,))
        if not row or row["status"] != "pending":
            return False
        if row["user_id"] != requester_id and requester_id != config.OWNER_ID:
            return False
        if channel_id is not None and row["channel_id"] != channel_id and requester_id != config.OWNER_ID:
            return False
        await self.db.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        return True

    async def cancel_latest_reminder(self, requester_id: int, channel_id: int) -> Optional[int]:
        row = await self.db.fetchone(
            """SELECT id FROM reminders
               WHERE channel_id = ? AND status = 'pending'
                 AND (user_id = ? OR ? = ?)
               ORDER BY created_at DESC LIMIT 1""",
            (channel_id, requester_id, requester_id, config.OWNER_ID),
        )
        if not row:
            return None
        return row["id"] if await self.cancel_reminder(row["id"], requester_id, channel_id=channel_id) else None

    # ---------------------------------------------------------- channel settings
    async def ensure_channel(
        self,
        channel_id: int,
        guild_id: Optional[int],
        channel_name: str,
        is_private_dm: bool = False,
    ) -> None:
        existing = await self.db.fetchone(
            "SELECT channel_id FROM channel_settings WHERE channel_id = ?", (channel_id,)
        )
        if not existing:
            await self.db.execute(
                """INSERT INTO channel_settings (channel_id, guild_id, channel_name, is_private_dm)
                   VALUES (?, ?, ?, ?)""",
                (channel_id, guild_id, channel_name, int(is_private_dm)),
            )
        else:
            # Channel objects can be cached before their type is known. Keep
            # the persisted privacy classification current on every message.
            await self.db.execute(
                """UPDATE channel_settings
                   SET guild_id = ?, channel_name = ?, is_private_dm = ?
                   WHERE channel_id = ?""",
                (guild_id, channel_name, int(is_private_dm), channel_id),
            )

    async def get_channel_settings(self, channel_id: int) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT * FROM channel_settings WHERE channel_id = ?", (channel_id,)
        )
        return dict(row) if row else None

    async def set_channel_autonomous(self, channel_id: int, enabled: bool) -> None:
        await self.db.execute(
            "UPDATE channel_settings SET autonomous_enabled = ? WHERE channel_id = ?",
            (int(enabled), channel_id),
        )

    async def set_channel_review_preview(self, channel_id: int, enabled: bool) -> None:
        await self.db.execute(
            "UPDATE channel_settings SET review_preview_enabled = ? WHERE channel_id = ?",
            (int(enabled), channel_id),
        )

    async def touch_channel_autonomous_post(self, channel_id: int) -> None:
        await self.db.execute(
            "UPDATE channel_settings SET last_autonomous_post = ? WHERE channel_id = ?",
            (time.time(), channel_id),
        )

    async def touch_channel_owner_dm(self, channel_id: int) -> None:
        await self.db.execute(
            "UPDATE channel_settings SET last_owner_dm = ? WHERE channel_id = ?",
            (time.time(), channel_id),
        )

    async def mark_channel_evaluated(
        self, channel_id: int, message_id: Optional[int]
    ) -> None:
        await self.db.execute(
            """UPDATE channel_settings
               SET last_autonomous_evaluation = ?, last_evaluated_message_id = ?
               WHERE channel_id = ?""",
            (time.time(), message_id, channel_id),
        )

    async def curiosity_allowed(
        self, user_id: int, channel_id: int, cooldown_seconds: float
    ) -> bool:
        row = await self.db.fetchone(
            """SELECT last_attempt FROM curiosity_state
               WHERE user_id = ? AND channel_id = ?""",
            (user_id, channel_id),
        )
        return not row or time.time() - (row["last_attempt"] or 0) >= cooldown_seconds

    async def touch_curiosity_attempt(
        self, user_id: int, channel_id: int, posted: bool = False
    ) -> None:
        now = time.time()
        await self.db.execute(
            """INSERT INTO curiosity_state (user_id, channel_id, last_attempt, last_post)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, channel_id) DO UPDATE SET
                   last_attempt = excluded.last_attempt,
                   last_post = CASE WHEN excluded.last_post > 0
                                    THEN excluded.last_post
                                    ELSE curiosity_state.last_post END""",
            (user_id, channel_id, now, now if posted else 0),
        )

    async def log_event(
        self,
        event_type: str,
        *,
        channel_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        batch_id: Optional[str] = None,
        message_ids: str = "",
        participant_ids: str = "",
        decision_id: Optional[int] = None,
        status: Optional[str] = None,
        latency_ms: Optional[float] = None,
        details: str = "",
    ) -> int:
        return await self.db.execute(
            """INSERT INTO interaction_events
               (timestamp, event_type, channel_id, guild_id, batch_id, message_ids,
                participant_ids, decision_id, status, latency_ms, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), event_type, channel_id, guild_id, batch_id,
                message_ids, participant_ids, decision_id, status, latency_ms, details,
            ),
        )

    async def count_events(self, event_type: str, since: Optional[float] = None) -> int:
        if since is None:
            row = await self.db.fetchone(
                "SELECT COUNT(*) AS count FROM interaction_events WHERE event_type = ?",
                (event_type,),
            )
        else:
            row = await self.db.fetchone(
                """SELECT COUNT(*) AS count FROM interaction_events
                   WHERE event_type = ? AND timestamp >= ?""",
                (event_type, since),
            )
        return int(row["count"] if row else 0)
