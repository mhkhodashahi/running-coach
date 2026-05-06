"""Pydantic response schemas for structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CoachingDecisionSchema(BaseModel):
    summary: str = Field(default="")
    yesterday_assessment: str = Field(default="")
    tomorrow_recommendation: str = Field(default="")
    weekly_outlook: str = Field(default="")
    goal_alignment: str = Field(default="")
    risk_level: Literal["low", "moderate", "high"] = "moderate"
    confidence: float = Field(default=0, ge=0, le=100)
    key_positives: list[str] = Field(default_factory=list)
    key_limiters: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    priority: str = Field(default="")


class TelegramMessageSchema(BaseModel):
    message_title: str = Field(default="")
    message_body: str = Field(default="")


class TelegramTrainingChatSchema(BaseModel):
    answer: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    follow_up: str = Field(default="")


class BodyScanInsightSchema(BaseModel):
    summary: str = Field(default="")
    visual_changes: list[str] = Field(default_factory=list)
    posture_and_symmetry: list[str] = Field(default_factory=list)
    running_form_implications: list[str] = Field(default_factory=list)
    progress_trends: list[str] = Field(default_factory=list)
    risks_or_unknowns: list[str] = Field(default_factory=list)
    coaching_actions: list[str] = Field(default_factory=list)
    next_photo_protocol: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=100)
