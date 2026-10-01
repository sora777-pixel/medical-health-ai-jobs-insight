"""Private storage for candidate profiles and match caches.

These files live under ``automation/state`` and are not published with the
dashboard JSON.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from ..store import read_json, utc_now_iso, write_json
from .models import CandidateProfile

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CareerStore:
    def __init__(self, state_dir: Path) -> None:
        root = Path(state_dir)
        self.candidates_dir = root / "candidates"
        self.matches_dir = root / "matches"

    def save_profile(self, profile: CandidateProfile) -> CandidateProfile:
        if profile.candidate_id:
            require_candidate_id(profile.candidate_id)
            existing = self.load_profile(profile.candidate_id)
        else:
            profile.candidate_id = new_candidate_id()
            existing = None
        now = utc_now_iso()
        if existing is not None and existing.created_at:
            profile.created_at = existing.created_at
        elif not profile.created_at:
            profile.created_at = now
        profile.updated_at = now
        write_json(self.candidates_dir / f"{profile.candidate_id}.json", profile.as_dict())
        return profile

    def load_profile(self, candidate_id: str) -> CandidateProfile | None:
        path = self.candidates_dir / f"{require_candidate_id(candidate_id)}.json"
        payload = read_json(path)
        if not isinstance(payload, dict):
            return None
        profile = CandidateProfile.from_dict(payload)
        profile.candidate_id = profile.candidate_id or candidate_id
        return profile

    def save_matches(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_id = require_candidate_id(candidate_id)
        body = {"candidate_id": safe_id, "generated_at": utc_now_iso(), **payload}
        write_json(self.matches_dir / f"{safe_id}.json", body)
        return body

    def load_matches(self, candidate_id: str) -> dict[str, Any] | None:
        path = self.matches_dir / f"{require_candidate_id(candidate_id)}.json"
        payload = read_json(path)
        return payload if isinstance(payload, dict) else None


def new_candidate_id() -> str:
    return f"cand-{uuid.uuid4().hex[:12]}"


def require_candidate_id(candidate_id: str) -> str:
    text = (candidate_id or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError("非法 candidate_id")
    return text
