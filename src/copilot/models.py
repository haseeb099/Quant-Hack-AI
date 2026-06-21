"""Pydantic schemas for copilot API responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DataCitation(BaseModel):
    source: str
    field: str
    value: Any
    timestamp: str | None = None


class AgentVoteSummary(BaseModel):
    agent: str
    direction: str
    confidence: float
    reasoning: str


class SymbolAnalysisResponse(BaseModel):
    symbol: str
    verdict: Literal["ALLOW", "WAIT", "BLOCK", "REFUSE"]
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    risks: list[str] = Field(default_factory=list)
    strategy: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    market: dict[str, Any] = Field(default_factory=dict)
    agent_consensus: list[AgentVoteSummary] = Field(default_factory=list)
    trade_check: dict[str, Any] = Field(default_factory=dict)
    data_citations: list[DataCitation] = Field(default_factory=list)
    provider: str = "template"
    refused: bool = False
    refusal_reason: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    symbol: str | None = None


class ChatResponse(BaseModel):
    message: str
    symbol: str | None = None
    analysis: SymbolAnalysisResponse | None = None
    provider: str = "template"
