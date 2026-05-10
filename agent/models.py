from __future__ import annotations
from typing import Any
import uuid
from pydantic import BaseModel, Field


class ToolFunction(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolSchema(BaseModel):
    type: str = "function"
    function: ToolFunction


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ChatResponse(BaseModel):
    message: Message
    done: bool = True
