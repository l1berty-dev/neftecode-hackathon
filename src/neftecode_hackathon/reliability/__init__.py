"""Reliability integration boundary; no unverified industrial proxy."""

from typing import Protocol

from neftecode_hackathon.contracts import Action, ProcessSnapshot, ReliabilityAssessment
from neftecode_hackathon.reliability.proxy import SeverityProxyAgent

__all__ = ["ReliabilityAgent", "SeverityProxyAgent", "UnavailableReliabilityAgent"]


class ReliabilityAgent(Protocol):
    def assess(self, snapshot: ProcessSnapshot, action: Action) -> ReliabilityAssessment: ...


class UnavailableReliabilityAgent:
    """Explicit absence of a verified reliability model, never a synthetic fallback."""

    def assess(self, snapshot: ProcessSnapshot, action: Action) -> ReliabilityAssessment:
        return ReliabilityAssessment(
            severity_index=None,
            factors=(),
            transition_assessed=False,
            limitations=(
                "Показатель тяжести режима не оценён: сигналы и нормировки не утверждены.",
                "Безопасность перехода к новым настройкам не оценена.",
            ),
        )
