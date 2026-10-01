from jobsinsight.career.skills import normalize_skill
from jobsinsight.llm import LLMError


def test_exact_and_case_insensitive_match():
    assert normalize_skill("Python").canonical_name == "Python"
    assert normalize_skill("PYTHON").canonical_name == "Python"
    assert normalize_skill("PyTorch").canonical_name == "PyTorch"


def test_alias_match_does_not_call_llm():
    class Spy:
        def __init__(self) -> None:
            self.calls = 0

        def task_json(self, **kwargs):
            self.calls += 1
            return {"canonical_name": "TensorFlow", "confident": True}

    spy = Spy()
    assert normalize_skill("torch", llm=spy).canonical_name == "PyTorch"
    assert normalize_skill("医学自然语言处理", llm=spy).canonical_name == "Medical NLP"
    assert normalize_skill("r语言", llm=spy).canonical_name == "R"
    assert spy.calls == 0


def test_unknown_term_may_call_llm_and_only_accepts_catalog_names():
    class Spy:
        def __init__(self) -> None:
            self.calls = 0

        def task_json(self, **kwargs):
            self.calls += 1
            return {"canonical_name": "PyTorch", "confident": True}

    spy = Spy()
    mapped = normalize_skill("某种冷门框架", llm=spy)
    assert spy.calls == 1
    assert mapped.canonical_name == "PyTorch"

    class Unsure:
        def task_json(self, **kwargs):
            return {"canonical_name": "PyTorch", "confident": False}

    assert normalize_skill("某种冷门框架", llm=Unsure()).canonical_name == "某种冷门框架"


def test_llm_failure_keeps_the_surface_form():
    class Boom:
        def task_json(self, **kwargs):
            raise LLMError("provider unavailable")

    skill = normalize_skill("某种冷门框架", llm=Boom())
    assert skill.canonical_name == "某种冷门框架"
    assert skill.level == "unknown"
