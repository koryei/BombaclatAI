"""Shared dataclasses used across the brain, decision engine, and persistence layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MessageRecord:
    user_id: int
    author_name: str
    content: str
    timestamp: float
    is_bot: bool = False
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    is_command: bool = False
    is_attachment_only: bool = False


@dataclass
class UserVibe:
    user_id: int
    energy: float = 0.5  # 0 = flat/chill, 1 = hyper
    formality: float = 0.4  # 0 = very casual, 1 = formal
    trust_score: float = 0.5
    interaction_count: int = 0
    message_count: int = 0
    question_count: int = 0
    emoji_count: int = 0


@dataclass
class Decision:
    should_post: bool
    trigger: Optional[str]
    confidence: float
    reasoning: str
    decision_id: Optional[int] = None
    action_type: str = "text"
    reaction_emoji: Optional[str] = None
    gif_category: Optional[str] = None


@dataclass
class PersonalityState:
    tone: str
    energy: float
    formality: float
    directive: str


@dataclass
class MemoryCandidate:
    about_user_id: int
    memory_text: str
    category: str = "fact"
    confidence: float = 0.6
    is_sensitive: bool = False
    guild_id: Optional[int] = None
    source_channel_id: Optional[int] = None
    source_is_private_dm: bool = False
    source_message_id: Optional[int] = None
    verified_by_owner: bool = False


@dataclass
class ChannelContext:
    channel_id: int
    guild_id: Optional[int]
    is_dm: bool = False
    messages: list = field(default_factory=list)
