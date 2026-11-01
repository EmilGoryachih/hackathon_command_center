"""Explainable, provider-free situation contracts. All timestamps are UTC."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SituationSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid')
    enabled: bool = False
    near_minutes: int = Field(default=60, ge=5, le=1440)
    reminder_minutes: int = Field(default=120, ge=30, le=10080)
    mention_captains: bool = True
    mention_participants: bool = True


class Situation(BaseModel):
    id: str
    project_id: int
    type: str
    status: Literal['active', 'resolved'] = 'active'
    level: Literal['attention', 'check']
    title: str
    text: str
    suggestion: str | None = None
    task_ids: list[int] = Field(default_factory=list)
    incident_ids: list[int] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    track_ids: list[int] = Field(default_factory=list)
    grounds: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    as_of: datetime
    first_seen_at: datetime | None = None
    changed_at: datetime | None = None
    resolved_at: datetime | None = None
    delivery_issue: str | None = None
