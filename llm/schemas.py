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


class ActivityCoachInsightSchema(BaseModel):
    overall_assessment: str = Field(default="")
    what_was_good: list[str] = Field(default_factory=list)
    mistakes_or_inefficiencies: list[str] = Field(default_factory=list)
    pacing_analysis: str = Field(default="")
    aerobic_efficiency_analysis: str = Field(default="")
    recovery_analysis: str = Field(default="")
    mental_performance_insights: str = Field(default="")
    training_recommendations: list[str] = Field(default_factory=list)
    brutally_honest_conclusion: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=100)


class ActiveIntelligenceInsightSchema(BaseModel):
    title: str = Field(default="")
    status: Literal["positive", "stable", "caution", "urgent"] = "stable"
    message: str = Field(default="")
    action: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=100)


class ActiveIntelligenceResponseSchema(BaseModel):
    summary: str = Field(default="")
    insights: list[ActiveIntelligenceInsightSchema] = Field(default_factory=list)
    next_check_in: str = Field(default="")
    limitations: list[str] = Field(default_factory=list)
