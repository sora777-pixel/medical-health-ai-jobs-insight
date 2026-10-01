from jobsinsight.career.gaps import calculate_skill_gaps
from jobsinsight.career.models import CandidateProfile, CandidateSkill
from jobsinsight.models import Job


def _job(job_id: int, *, title: str, skills: list[str]) -> Job:
    return Job(
        id=job_id,
        platform="test",
        title=title,
        company="Lab",
        city="上海",
        salary_min=30,
        salary_max=40,
        experience="3-5年",
        education="硕士",
        skills=skills,
        category="AI药物研发",
        summary="药物发现方向",
    )


def test_missing_skills_are_aggregated_by_frequency_and_core():
    candidate = CandidateProfile(
        years_experience=3,
        education="硕士",
        skills=[
            CandidateSkill(name="Python", canonical_name="Python"),
            CandidateSkill(name="PyTorch", canonical_name="PyTorch"),
            CandidateSkill(name="Bioinformatics", canonical_name="Bioinformatics"),
        ],
        domains=["AI Drug Discovery"],
        target_categories=["AI药物研发"],
        target_cities=["上海"],
        target_roles=["AI药物研发"],
    )
    jobs = []
    for index in range(1, 9):
        skills = ["Python", "PyTorch", "Bioinformatics", "RDKit", "SQL"]
        title = f"RDKit 药物算法工程师 {index}"
        if index <= 3:
            skills = ["Python", "PyTorch", "Bioinformatics", "RDKit", "GNN", "SQL"]
        if index == 8:
            skills = ["Python", "PyTorch", "Bioinformatics", "RDKit", "FHIR", "SQL"]
        jobs.append(_job(index, title=title, skills=skills))

    gaps = {gap.skill: gap for gap in calculate_skill_gaps(candidate, jobs, top_k=20)}

    assert gaps["RDKit"].priority == "high"
    assert gaps["RDKit"].frequency == 8
    assert "8" in gaps["RDKit"].reason
    assert "AI药物研发" in gaps["RDKit"].reason
    assert gaps["GNN"].priority == "medium"
    assert gaps["GNN"].frequency == 3
    assert gaps["GNN"].reason == "在多个岗位出现，但不是全部岗位的核心要求"
    assert gaps["FHIR"].priority == "low"
    assert gaps["FHIR"].frequency == 1
    assert set(gaps["RDKit"].related_jobs) == set(range(1, 9))


def test_empty_inputs_produce_no_gaps():
    candidate = CandidateProfile(skills=[CandidateSkill(name="Python", canonical_name="Python")])
    assert calculate_skill_gaps(candidate, []) == []
    assert calculate_skill_gaps(CandidateProfile(), [_job(1, title="RDKit", skills=["RDKit"])]) == []
