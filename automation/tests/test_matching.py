import pytest

from jobsinsight.career.matching import (
    calculate_education_score,
    calculate_experience_score,
    calculate_location_score,
    match_candidate_to_job,
    rank_jobs,
)
from jobsinsight.career.models import CandidateProfile, CandidateSkill
from jobsinsight.career.tools import get_job, get_market_skill_trend, search_jobs
from jobsinsight.models import Job


def _profile(**overrides) -> CandidateProfile:
    payload = {
        "years_experience": 3,
        "education": "硕士",
        "skills": [CandidateSkill(name="Python", canonical_name="Python")],
        "domains": ["Bioinformatics"],
        "target_categories": ["生物信息"],
        "target_cities": ["上海"],
        "target_roles": ["Bioinformatics Scientist"],
        "salary_min": 25,
    }
    payload.update(overrides)
    return CandidateProfile(**payload)


def _job(**overrides) -> Job:
    payload = {
        "id": 1,
        "platform": "test",
        "title": "Bioinformatics Scientist",
        "company": "Lab",
        "city": "上海",
        "salary_min": 20,
        "salary_max": 40,
        "experience": "3-5年",
        "education": "硕士",
        "skills": ["Python"],
        "category": "生物信息",
    }
    payload.update(overrides)
    return Job(**payload)


def test_exact_skill_match_and_missing_skills():
    profile = _profile(
        skills=[
            CandidateSkill(name="Python", canonical_name="Python"),
            CandidateSkill(name="PyTorch", canonical_name="PyTorch"),
            CandidateSkill(name="Bioinformatics", canonical_name="Bioinformatics"),
            CandidateSkill(name="SQL", canonical_name="SQL"),
        ],
        salary_min=0,
        target_cities=[],
    )
    result = match_candidate_to_job(
        profile,
        _job(skills=["Python", "PyTorch", "Bioinformatics", "RDKit", "GNN"], title="Scientist"),
    )

    assert result.matched_skills == ["Python", "PyTorch", "Bioinformatics"]
    assert result.missing_skills == ["RDKit", "GNN"]
    assert result.nice_to_have == ["SQL"]
    assert result.breakdown.skill == 60


def test_alias_skill_match():
    profile = _profile(skills=[CandidateSkill(name="torch")], salary_min=0)
    result = match_candidate_to_job(profile, _job(skills=["PyTorch", "药物研发"]))

    assert "PyTorch" in result.matched_skills
    assert "Drug Discovery" in result.missing_skills


def test_no_skill_match():
    profile = _profile(skills=[CandidateSkill(name="Cooking", canonical_name="Cooking")], salary_min=0)
    result = match_candidate_to_job(profile, _job(skills=["Python", "RDKit"]))

    assert result.matched_skills == []
    assert result.missing_skills == ["Python", "RDKit"]
    assert result.breakdown.skill == 0


def test_unknown_salary_is_not_penalised():
    result = match_candidate_to_job(_profile(salary_min=0), _job(salary_min=10, salary_max=18))
    assert result.breakdown.salary is None

    unknown_job = match_candidate_to_job(_profile(salary_min=25), _job(salary_min=0, salary_max=0))
    assert unknown_job.breakdown.salary == 100


def test_salary_below_expectation_is_reduced():
    result = match_candidate_to_job(_profile(salary_min=25), _job(salary_min=10, salary_max=18))
    assert result.breakdown.salary == pytest.approx(28.8, abs=0.1)
    met = match_candidate_to_job(_profile(salary_min=25), _job(salary_max=30))
    assert met.breakdown.salary == 100


def test_unknown_location_is_not_a_mismatch():
    assert calculate_location_score(_profile(target_cities=[]), _job(city="北京")) == 100
    assert calculate_location_score(_profile(target_cities=["上海市", "杭州"]), _job(city="上海")) == 100
    assert calculate_location_score(_profile(target_cities=["Shanghai"]), _job(city="上海市")) == 100
    assert calculate_location_score(_profile(target_cities=["上海", "杭州"]), _job(city="北京")) == 20


def test_experience_boundaries():
    assert calculate_experience_score(_profile(years_experience=3), _job(experience="3-5年")) == 100
    assert calculate_experience_score(_profile(years_experience=5), _job(experience="5-10年")) == 100
    assert calculate_experience_score(_profile(years_experience=10), _job(experience="10年以上")) == 100
    assert calculate_experience_score(_profile(years_experience=1), _job(experience="5-10年")) == 20
    assert calculate_experience_score(_profile(years_experience=0), _job(experience="3-5年")) is None
    freshman = CandidateProfile(years_experience=0, profile_text="应届生")
    assert calculate_experience_score(freshman, _job(experience="应届")) == 100


def test_education_boundaries():
    assert calculate_education_score(_profile(education="硕士"), _job(education="本科")) == 100
    assert calculate_education_score(_profile(education="本科"), _job(education="博士")) == 25
    assert calculate_education_score(_profile(education=""), _job(education="硕士")) is None
    assert calculate_education_score(_profile(education="硕士"), _job(education="")) == 100
    assert calculate_education_score(_profile(education="硕士"), _job(education="未知")) == 100


def test_missing_salary_renormalises_weights():
    profile = _profile(
        salary_min=0,
        skills=[CandidateSkill(name="Python", canonical_name="Python")],
    )
    result = match_candidate_to_job(profile, _job(skills=["Python", "RDKit"], title="Bioinformatics Scientist"))

    assert result.breakdown.salary is None
    assert result.available_weight == 95
    # skill 50 * 40, every other available dimension is 100. 75 / 95 * 100.
    assert result.overall_score == pytest.approx(78.9, abs=0.1)
    assert result.overall_score != 75


def test_role_aliases_and_domain_overlap():
    medical = match_candidate_to_job(
        _profile(target_roles=["Medical AI Engineer"], domains=["Medical AI"], target_categories=["医疗大模型"]),
        _job(title="Healthcare AI Engineer", category="医疗大模型", skills=["Python"]),
    )
    assert medical.breakdown.role == 100

    adjacent = match_candidate_to_job(
        _profile(target_roles=["Bioinformatics Scientist"], domains=["Bioinformatics"]),
        _job(title="AI Drug Discovery Scientist", category="AI药物研发", skills=["Python"]),
    )
    assert adjacent.breakdown.role >= 70


def test_empty_jobs_and_empty_profile():
    profile = _profile()
    assert rank_jobs(profile, []) == []

    empty = CandidateProfile()
    result = match_candidate_to_job(empty, _job(city="北京", skills=["Python", "RDKit"]))
    assert result.breakdown.salary is None
    assert result.breakdown.location == 100
    assert result.breakdown.skill is None
    assert result.missing_skills == []
    assert result.confidence < 0.2
    assert result.overall_score >= 0


def test_explanation_does_not_rewrite_the_score():
    class Hijack:
        def task_json(self, **kwargs):
            return {
                "reasons": ["已匹配技能：Python"],
                "strengths": ["Python"],
                "gaps": [],
                "summary": "说明",
                "overall_score": 1,
            }

    results = rank_jobs(_profile(salary_min=0), [_job()], llm=Hijack(), explain_limit=5)
    assert results[0].overall_score > 50
    assert results[0].explanation["summary"] == "说明"


def test_explanations_are_limited_to_top_k_slice():
    class Counter:
        def __init__(self) -> None:
            self.calls = 0

        def task_json(self, **kwargs):
            self.calls += 1
            return {"reasons": ["已匹配技能：Python"], "strengths": ["Python"], "gaps": [], "summary": "s"}

    jobs = [_job(id=index, title="Bioinformatics Scientist") for index in range(1, 13)]
    counter = Counter()
    results = rank_jobs(_profile(salary_min=0), jobs, top_k=12, llm=counter, explain_limit=10)

    assert len(results) == 12
    assert counter.calls == 10


def test_future_tool_boundary_reads_jobs_without_scoring_via_llm():
    jobs = [_job(), _job(id=2, city="北京", title="其他岗位", category="其他", skills=["SQL"])]
    assert get_job(jobs, 2)["city"] == "北京"
    assert search_jobs(jobs, city="上海", skill="Python")[0]["id"] == 1
    trend = get_market_skill_trend(jobs)
    assert trend[0]["skill"] == "Python"
