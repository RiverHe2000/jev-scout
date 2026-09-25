"""Validated public inputs; no browser-controlled credentials or upstream URLs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["baseline", "jev", "llm"]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Preference(StrictInput):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=5, max_length=500)
    weight: float = Field(default=1.0, ge=0, le=2)


class ProfileInput(StrictInput):
    name: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=10, max_length=3000)
    preferences: list[Preference] = Field(default_factory=list, max_length=3)
    exclusions: str = Field(default="", max_length=1500)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    seed_papers: list[str] = Field(default_factory=list, max_length=5)
    daily_limit: int = Field(default=10, ge=1, le=50)
    confidence_threshold: float = Field(default=0.65, ge=0, le=1)

    @field_validator("keywords", "seed_papers")
    @classmethod
    def bounded_strings(cls, values: list[str]) -> list[str]:
        values = [value.strip() for value in values if value.strip()]
        if any(len(value) > 200 for value in values):
            raise ValueError("Each entry must be no longer than 200 characters.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def unique_preferences(self) -> ProfileInput:
        if len({item.id for item in self.preferences}) != len(self.preferences):
            raise ValueError("Preference identifiers must be unique.")
        return self


class ProfileUpdate(ProfileInput):
    expected_version: int = Field(ge=1)


class ArchiveInput(StrictInput):
    archived: bool = True


class ReadingInput(StrictInput):
    profile_id: str = Field(min_length=1, max_length=100)
    saved: bool | None = None
    status: Literal["unread", "reading", "done"] | None = None
    note: str | None = Field(default=None, max_length=20000)
    feedback: Literal["useful", "not_now", "irrelevant"] | None = None


class IngestInput(StrictInput):
    profile_id: str = Field(min_length=1, max_length=100)
    query: str | None = Field(default=None, max_length=1000)
    ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    max_results: int = Field(default=30, ge=1, le=100)
    mode: Mode = "baseline"

    @model_validator(mode="after")
    def exactly_one_source(self) -> IngestInput:
        if self.query == "":
            self.query = None
        if bool(self.query) == bool(self.ids):
            raise ValueError("Provide either an arXiv query or a list of arXiv IDs.")
        if self.query and any(ord(character) < 32 for character in self.query):
            raise ValueError("An arXiv query cannot contain control characters.")
        if self.ids and any(not value or len(value) > 250 for value in self.ids):
            raise ValueError("An arXiv identifier is too long.")
        return self


class EvaluateInput(StrictInput):
    profile_id: str = Field(min_length=1, max_length=100)
    mode: Mode = "baseline"
    paper_ids: list[str] | None = Field(default=None, max_length=1000)
    force: bool = False

    @field_validator("paper_ids")
    @classmethod
    def valid_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is not None:
            if any(not value or len(value) > 100 for value in values):
                raise ValueError("Paper IDs must be nonempty and bounded.")
            return list(dict.fromkeys(values))
        return None


class AnnotationInput(StrictInput):
    profile_id: str
    paper_id: str
    relevance: int = Field(ge=0, le=2)
    split: Literal["development", "calibration", "test"] = "test"
    note: str = Field(default="", max_length=2000)
