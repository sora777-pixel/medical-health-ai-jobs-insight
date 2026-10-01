from jobsinsight.career.profile import parse_candidate_profile
from jobsinsight.llm import LLMError

EXAMPLE = """我有3年生物信息学经验，硕士学历。
熟悉 Python、PyTorch、Docker、Linux、scRNA-seq。
做过单细胞数据分析和深度学习项目。
想转医疗AI或AI药物研发。
希望上海或杭州，薪资25K以上。"""


def test_example_profile_extracts_only_stated_facts():
    profile = parse_candidate_profile(EXAMPLE)

    assert profile.years_experience == 3
    assert profile.education == "硕士"
    assert profile.education_field == "生物信息学"
    names = {skill.canonical_name for skill in profile.skills}
    assert {"Python", "PyTorch", "Docker", "Linux", "scRNA-seq", "Deep Learning"} <= names
    assert "Drug Discovery" not in names
    assert "RAG" not in names
    assert all(skill.level == "unknown" for skill in profile.skills)
    python = next(skill for skill in profile.skills if skill.canonical_name == "Python")
    assert python.years == 0
    assert profile.target_cities == ["上海", "杭州"]
    assert profile.salary_min == 25
    assert profile.salary_max == 0
    assert "医疗AI" in profile.target_roles
    assert "AI药物研发" in profile.target_roles
    assert "AI药物研发" in profile.target_categories
    assert "Bioinformatics" in profile.domains


def test_familiar_skill_stays_unknown_level():
    profile = parse_candidate_profile("熟悉 Python")

    assert len(profile.skills) == 1
    assert profile.skills[0].canonical_name == "Python"
    assert profile.skills[0].level == "unknown"
    assert profile.skills[0].years == 0
    assert profile.years_experience == 0
    assert profile.education == ""


def test_explicit_skill_years_are_kept():
    profile = parse_candidate_profile("用了三年 Python")

    assert profile.skills[0].canonical_name == "Python"
    assert profile.skills[0].years == 3
    assert profile.skills[0].level == "unknown"
    assert profile.years_experience == 0


def test_learning_intent_is_not_a_current_skill():
    profile = parse_candidate_profile("熟悉 Python。想学习 RAG。")

    assert [skill.canonical_name for skill in profile.skills] == ["Python"]
    assert [skill.canonical_name for skill in profile.target_skills] == ["RAG"]


def test_llm_failure_falls_back_to_heuristic():
    class Boom:
        def task_json(self, **kwargs):
            raise LLMError("timeout")

    profile = parse_candidate_profile("熟悉 Python，硕士，有3年经验", llm=Boom())

    assert profile.skills[0].canonical_name == "Python"
    assert profile.education == "硕士"
    assert profile.years_experience == 3


def test_malformed_llm_json_falls_back():
    class Garbage:
        def task_json(self, **kwargs):
            return ["not-an-object"]

    profile = parse_candidate_profile("熟悉 Linux", llm=Garbage())

    assert [skill.canonical_name for skill in profile.skills] == ["Linux"]


def test_llm_cannot_invent_skills_or_years():
    class Invent:
        def task_json(self, **kwargs):
            return {
                "years_experience": 12,
                "education": "博士",
                "salary_min": 80,
                "target_cities": ["北京"],
                "skills": [
                    {
                        "name": "RDKit",
                        "canonical_name": "RDKit",
                        "level": "advanced",
                        "years": 4,
                        "evidence": "invented",
                    }
                ],
            }

    profile = parse_candidate_profile("熟悉 Python", llm=Invent())

    assert [skill.canonical_name for skill in profile.skills] == ["Python"]
    assert profile.skills[0].level == "unknown"
    assert profile.years_experience == 0
    assert profile.education == ""
    assert profile.salary_min == 0
    assert profile.target_cities == []


def test_profile_round_trips_through_json():
    profile = parse_candidate_profile(EXAMPLE)
    restored = type(profile).from_dict(profile.as_dict())

    assert restored.education == "硕士"
    assert restored.skills[0].canonical_name == profile.skills[0].canonical_name
    assert restored.target_cities == ["上海", "杭州"]
