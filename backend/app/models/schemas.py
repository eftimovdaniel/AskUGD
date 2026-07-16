from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


class Source(BaseModel):
    title: str
    url: str | None = None
    article_no: str | None = None
    source: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    session_id: str
