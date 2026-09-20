"""Validated replay episodes chosen only from the untouched historical period."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplayEpisode(BaseModel):
    """Internal replay configuration; public HTTP models live in the API package."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    name: Annotated[str, Field(min_length=1)]
    start: datetime
    end: datetime
    step_minutes: Literal[10] = 10
    synthetic: bool
    limitations: tuple[Annotated[str, Field(min_length=1)], ...] = ()

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        for field, value in (("start", self.start), ("end", self.end)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field} must include a timezone offset")
        if self.start >= self.end:
            raise ValueError("replay episode start must precede end")
        seconds = (self.end - self.start).total_seconds()
        if seconds % (self.step_minutes * 60):
            raise ValueError("replay episode bounds must align to the configured step")
        return self

    @property
    def positions(self) -> int:
        return int((self.end - self.start).total_seconds() // (self.step_minutes * 60)) + 1

    def timestamp_at(self, position: int) -> datetime:
        if not 0 <= position < self.positions:
            raise IndexError(position)
        return self.start + timedelta(minutes=self.step_minutes * position)


class ReplayCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Annotated[str, Field(min_length=1)]
    episodes: tuple[ReplayEpisode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({episode.episode_id for episode in self.episodes}) != len(self.episodes):
            raise ValueError("duplicate replay episode IDs")
        return self

    def get(self, episode_id: str) -> ReplayEpisode | None:
        return next(
            (episode for episode in self.episodes if episode.episode_id == episode_id), None
        )


def load_replay_catalogue(path: Path = Path("config/replay.yaml")) -> ReplayCatalogue:
    return ReplayCatalogue.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
