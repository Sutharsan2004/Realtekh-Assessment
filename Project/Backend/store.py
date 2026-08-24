"""
Simple in-memory store. Swap for a real DB by re-implementing this module's
functions with the same signatures.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from models import Candidate

_CANDIDATES: Dict[str, Candidate] = {}


def save(candidate: Candidate) -> None:
    _CANDIDATES[candidate.id] = candidate


def get(candidate_id: str) -> Optional[Candidate]:
    return _CANDIDATES.get(candidate_id)


def list_all() -> List[Candidate]:
    return sorted(_CANDIDATES.values(), key=lambda c: c.created_at, reverse=True)


def exists(candidate_id: str) -> bool:
    return candidate_id in _CANDIDATES
