"""Shared value object for provider-neutral coaching skills."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CoachSkill:
    """A bounded coaching playbook; application code still owns decisions."""

    id: str
    name: str
    workflows: tuple[str, ...]
    instructions: str
    required_context: tuple[tuple[str, str | bool], ...] = ()
