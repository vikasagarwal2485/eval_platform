import pytest
from pydantic import ValidationError

from app.schemas import CaseIn


def base(**kw):
    d = dict(category="classification", prompt="I love it", labels=["positive", "negative"], expected="positive")
    d.update(kw)
    return d


def test_valid_cases_for_each_category():
    assert CaseIn(**base()).to_config() == {"labels": ["positive", "negative"]}
    r = CaseIn(category="reasoning", prompt="2+2?", expected="4", comparison="numeric", tolerance=0.01)
    assert r.to_config() == {"comparison": "numeric", "tolerance": 0.01}
    g = CaseIn(
        category="generation",
        prompt="Write a haiku",
        constraints={"max_words": 30},
        rubric=[{"name": "Creativity"}],
    )
    assert g.expected is None
    assert g.to_config()["constraints"]["max_words"] == 30
    assert g.to_rubric() == [{"name": "Creativity", "description": ""}]


@pytest.mark.parametrize("prompt", ["", "   \n"])
def test_empty_prompt_rejected(prompt):
    with pytest.raises(ValidationError, match="prompt"):
        CaseIn(**base(prompt=prompt))


def test_unknown_category_rejected():
    with pytest.raises(ValidationError, match="category"):
        CaseIn(**base(category="summarization"))


def test_expected_label_must_be_in_labels():
    with pytest.raises(ValidationError, match="allowed labels"):
        CaseIn(**base(expected="neutral"))


def test_expected_label_matches_after_normalization():
    assert CaseIn(**base(expected="  Positive. ")).expected == "  Positive. "


def test_classification_needs_two_unique_labels():
    with pytest.raises(ValidationError, match="at least two"):
        CaseIn(**base(labels=["only"], expected=None))
    with pytest.raises(ValidationError, match="unique"):
        CaseIn(**base(labels=["a", "A"], expected=None))


def test_numeric_expected_must_parse():
    with pytest.raises(ValidationError, match="numeric"):
        CaseIn(category="reasoning", prompt="x", expected="abc", comparison="numeric")


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        CaseIn(**base(bogus=1))
