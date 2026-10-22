"""Pydantic response schemas for structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Intent = Literal["recovery", "easy", "steady", "tempo", "race"]


class OpinionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planned: Intent | None = None
    detected: Intent


class OpinionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspect: str
    rating: Literal["good", "watch", "poor"]
    word: str


class OpinionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: str
    detail: str = ""


class OpinionSections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pacing: str = ""
    aerobic: str = ""
    recovery: str = ""
    mental: str = ""


class OpinionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    action: Literal["add_to_plan", "reminder", "none"] = "none"
    session: dict = Field(default_factory=dict)


class OpinionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    value: str
    source: str


class CoachOpinionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    headline: str
    confidence: Literal["high", "medium", "low"]
    conclusion: str = ""
    assessment: str
    intent: OpinionIntent
    verdicts: list[OpinionVerdict] = Field(default_factory=list)
    worked: list[OpinionPoint] = Field(default_factory=list)
    fix: list[OpinionPoint] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)
    sections: OpinionSections = Field(default_factory=OpinionSections)
    recommendations: list[OpinionRecommendation] = Field(default_factory=list)
    evidence: list[OpinionEvidence] = Field(default_factory=list)


class OpenAIOpinionSession(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenAIOpinionRecommendation(OpinionRecommendation):
    session: OpenAIOpinionSession = Field(default_factory=OpenAIOpinionSession)


class OpenAICoachOpinionV2(CoachOpinionV2):
    recommendations: list[OpenAIOpinionRecommendation] = Field(default_factory=list)


class OpinionVerdictV21(OpinionVerdict):
    aspect: Literal["Pacing", "Intensity vs plan", "Aerobic stimulus", "HR control"]

    @field_validator("word")
    @classmethod
    def short_runner_word(cls, value: str) -> str:
        words = value.split()
        if not 1 <= len(words) <= 2 or not all(word.isalpha() for word in words):
            raise ValueError("word must be one or two plain words")
        return value

    @model_validator(mode="after")
    def word_matches_rating(self) -> OpinionVerdictV21:
        positive = {"good", "controlled", "steady", "strong", "efficient", "stable"}
        negative = {"too hard", "too fast", "too slow", "poor", "missed", "overcooked"}
        word = self.word.casefold()
        if (word in positive and self.rating != "good") or (word in negative and self.rating == "good"):
            raise ValueError("verdict word contradicts quality rating")
        if word == "moderate" and self.rating != "watch":
            raise ValueError("Moderate requires a watch rating")
        return self


class EmptyOpinionSession(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedOpinionSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sport: Literal["running", "volleyball", "football", "gym"]
    intent: Intent
    duration_min: int = Field(gt=0)
    hr_cap_bpm: int = Field(gt=0)


class OpinionRecommendationV21(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    action: Literal["add_to_plan", "reminder", "none"] = "none"
    session: EmptyOpinionSession | PlannedOpinionSession = Field(default_factory=EmptyOpinionSession)

    @model_validator(mode="after")
    def action_matches_session(self) -> OpinionRecommendationV21:
        if (self.action == "add_to_plan") != isinstance(self.session, PlannedOpinionSession):
            raise ValueError("add_to_plan requires a complete session; other actions require {}")
        return self


class CoachOpinionV21(CoachOpinionV2):
    verdicts: list[OpinionVerdictV21] = Field(default_factory=list)
    recommendations: list[OpinionRecommendationV21] = Field(default_factory=list)
    evidence: list[OpinionEvidence] = Field(default_factory=list, min_length=4, max_length=10)


class OpinionVerdictV22(OpinionVerdict):
    aspect: Literal["Pacing", "Intensity vs plan", "Aerobic stimulus", "HR control"]

    @field_validator("word")
    @classmethod
    def runner_word(cls, value: str) -> str:
        words = value.split()
        if not 1 <= len(words) <= 3 or not all(word.isalpha() for word in words):
            raise ValueError("word must be one to three plain words")
        return value


class OpinionDraftV22(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    conclusion: str = ""
    assessment: str
    verdicts: list[OpinionVerdictV22] = Field(default_factory=list)
    worked: list[OpinionPoint] = Field(default_factory=list)
    fix: list[OpinionPoint] = Field(default_factory=list)
    sections: OpinionSections = Field(default_factory=OpinionSections)
    recommendations: list[OpinionRecommendationV21] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=4, max_length=10)


class CoachOpinionV22(CoachOpinionV2):
    verdicts: list[OpinionVerdictV22] = Field(default_factory=list)
    recommendations: list[OpinionRecommendationV21] = Field(default_factory=list)
    evidence: list[OpinionEvidence] = Field(default_factory=list, min_length=4, max_length=10)


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
