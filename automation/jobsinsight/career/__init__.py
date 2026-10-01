"""Healthcare AI career copilot: profile, match, and skill gap.

The functions below are the stable boundary a later agent layer can wrap.
They do not replace the recruiting pipeline.
"""

from .explain import generate_match_explanation
from .gaps import calculate_skill_gaps
from .matching import match_candidate_to_job, rank_jobs
from .profile import parse_candidate_profile
from .skills import normalize_skill
from .tools import analyze_skill_gap, get_job, get_market_skill_trend, match_candidate, search_jobs

__all__ = [
    "analyze_skill_gap",
    "calculate_skill_gaps",
    "generate_match_explanation",
    "get_job",
    "get_market_skill_trend",
    "match_candidate",
    "match_candidate_to_job",
    "normalize_skill",
    "parse_candidate_profile",
    "rank_jobs",
    "search_jobs",
]
