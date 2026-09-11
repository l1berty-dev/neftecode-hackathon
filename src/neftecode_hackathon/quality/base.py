"""Public interface consumed by scenario evaluation and orchestration."""

from typing import Protocol

from neftecode_hackathon.contracts import Action, ProcessSnapshot, QualityAssessment


class QualityAgent(Protocol):
    """Assess output quality for one snapshot/action/horizon combination."""

    def assess(
        self,
        snapshot: ProcessSnapshot,
        action: Action,
        horizon_minutes: int,
    ) -> QualityAssessment: ...
