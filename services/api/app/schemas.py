# services/api/app/schemas.py

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Tag(BaseModel):
    name: str


class BotBase(BaseModel):
    title: str = Field(..., description="Display title of the bot")
    name: str = Field(..., description="Short internal name of the bot")
    description: Optional[str] = Field(None, description="What this bot does")
    persona: str = Field(default="", description="Bot persona/personality description")
    tags: List[str] = Field(default_factory=list, description="Simple list of tag names")
    avatar_url: Optional[str] = Field(None, description="URL to bot's profile picture")
    scenario: Optional[str] = Field(None, description="Brief scenario description (sent only on first message)")
    greeting: Optional[str] = Field(None, description="Initial greeting message (always added when creating new chat)")
    example_dialog: Optional[str] = Field(None, description="Example dialog showing how the character talks (always sent to LLM)")


class BotCreate(BotBase):
    pass


class BotUpdate(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    persona: Optional[str] = None
    tags: Optional[List[str]] = None
    avatar_url: Optional[str] = None
    scenario: Optional[str] = None
    greeting: Optional[str] = None
    example_dialog: Optional[str] = None


class BotOut(BotBase):
    bot_id: int


class MessageOut(BaseModel):
    message_id: int
    sender: str  # "user" or "bot"
    content: str
    created_at: datetime
    parent_message_id: Optional[int] = None
    attempt_number: Optional[int] = None
    is_selected: Optional[bool] = None
    total_attempts: Optional[int] = None  # Total number of attempts for this message


class MessageUpdate(BaseModel):
    content: str


class ChatCreate(BaseModel):
    bot_id: int
    title: Optional[str] = None
    persona_id: Optional[int] = None
    model_id: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None

class ChatUpdate(BaseModel):
    title: Optional[str] = None
    persona_id: Optional[int] = None
    model_id: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


class ChatSummary(BaseModel):
    chat_id: str
    title: str
    bot_id: int
    bot_name: str
    last_used: Optional[datetime] = None
    persona_id: Optional[int] = None
    persona_avatar_url: Optional[str] = None
    message_count: Optional[int] = None
    model_id: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


class ChatDetail(BaseModel):
    chat_id: str
    title: str
    bot_id: int
    bot_name: str
    persona_id: Optional[int] = None
    persona_name: Optional[str] = None
    model_id: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    history: List[MessageOut]


class GenerationSettingsIn(BaseModel):
    """Generation settings that can be passed with a message."""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


class ChatMessageIn(BaseModel):
    message: str
    commit_previous: bool = Field(default=True, description="Whether to commit any pending bot reply before sending this message")
    generation_settings: Optional[GenerationSettingsIn] = None


class ChatMessageResponse(BaseModel):
    chat: ChatDetail
    bot_reply: str
