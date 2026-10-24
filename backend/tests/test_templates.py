from app.core.templates import apply_skills


def test_no_skills_leaves_system_prompt_unchanged():
    assert apply_skills("be nice", None) == "be nice"
    assert apply_skills("be nice", []) == "be nice"
    assert apply_skills(None, []) is None


def test_one_skill_with_no_case_system_prompt():
    out = apply_skills(None, [{"id": 1, "name": "step-by-step", "instructions": "Think step by step."}])
    assert "Think step by step." in out and "step-by-step" in out


def test_multiple_skills_both_present_in_order():
    skills = [
        {"id": 1, "name": "a", "instructions": "Do A first."},
        {"id": 2, "name": "b", "instructions": "Then do B."},
    ]
    out = apply_skills(None, skills)
    assert out.index("Do A first.") < out.index("Then do B.")


def test_skill_combined_with_case_system_prompt_skill_first():
    out = apply_skills("Be concise.", [{"id": 1, "name": "a", "instructions": "Do A."}])
    assert "Do A." in out and "Be concise." in out
    assert out.index("Do A.") < out.index("Be concise.")
