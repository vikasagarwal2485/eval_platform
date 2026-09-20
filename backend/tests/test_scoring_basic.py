import pytest

from app.core.scoring.classification import classification_metrics, predict_label, score_classification
from app.core.scoring.reasoning import extract_final_answer, score_reasoning
from app.core.scoring.thinking import split_thinking
from app.core.templates import TEMPLATE_VERSION, build_messages, build_prompt

LABELS = ["positive", "negative", "neutral"]


# ------------------------------------------------------------------ 5.1 templates
def test_classification_suffix_lists_labels_and_version():
    sent, ver = build_prompt("classification", "Great phone", {"labels": LABELS})
    assert sent.startswith("Great phone")
    assert "exactly one of these labels" in sent and "positive, negative, neutral" in sent
    assert ver == TEMPLATE_VERSION == "v1"


def test_reasoning_suffix_requests_final_answer_marker():
    sent, ver = build_prompt("reasoning", "2+2?", {})
    assert "Final answer:" in sent and ver == "v1"


def test_generation_prompt_unchanged():
    assert build_prompt("generation", "Write a haiku", {})[0] == "Write a haiku"


def test_messages_include_system_prompt_when_given():
    assert build_messages("be brief", "hi") == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert build_messages(None, "hi") == [{"role": "user", "content": "hi"}]


# ------------------------------------------------------------------ 5.2 thinking split
def test_structured_thinking_field():
    assert split_thinking("Final answer: 5", "Let me add.") == ("Final answer: 5", "Let me add.")


def test_inline_think_tags_are_stripped():
    ans, trace = split_thinking("<think>\nhmm 2+3\n</think>\n\nThe answer is 5")
    assert ans == "The answer is 5" and trace == "hmm 2+3"


def test_unterminated_think_leaves_empty_answer():
    ans, trace = split_thinking("<think>still thinking about")
    assert ans == "" and trace == "still thinking about"


def test_no_reasoning():
    assert split_thinking("positive") == ("positive", None)
    assert split_thinking("positive", "  ") == ("positive", None)


def test_field_and_inline_are_merged():
    ans, trace = split_thinking("<think>b</think>done", "a")
    assert ans == "done" and trace == "a\n\nb"


# ------------------------------------------------------------------ 5.3 classification
@pytest.mark.parametrize(
    "answer,expected,value,outcome",
    [
        ("Positive.", "positive", 1.0, "correct"),
        ("  POSITIVE \n", "positive", 1.0, "correct"),
        ("negative", "positive", 0.0, "wrong"),
        ("The sentiment is positive.", "positive", 1.0, "correct"),
        ("I have no idea", "positive", 0.0, "unparseable"),
        ("", "positive", 0.0, "unparseable"),
        ("positive", None, None, "unscored"),
    ],
)
def test_score_classification(answer, expected, value, outcome):
    r = score_classification(answer, LABELS, expected)
    assert (r.value, r.outcome) == (value, outcome)


def test_multiple_labels_first_mention_wins_and_ambiguity_flagged():
    label, d = predict_label("positive, although some might say negative", LABELS)
    assert label == "positive" and d["ambiguous"] is True and d["candidates"] == ["positive", "negative"]


def test_explicit_marker_beats_earlier_mentions():
    label, d = predict_label("Positive words appear but overall.\nLabel: negative", LABELS)
    assert label == "negative" and d["method"] == "marker"


def test_label_contained_in_longer_label():
    labels = ["spam", "not_spam"]
    assert predict_label("not spam", labels)[0] == "not_spam"
    assert predict_label("not_spam", labels)[0] == "not_spam"
    assert predict_label("This is spam", labels)[0] == "spam"


def test_underscore_labels_match_spaced_text():
    labels = ["cancel_subscription", "billing_question"]
    assert predict_label("cancel subscription", labels)[0] == "cancel_subscription"


def test_no_partial_word_match():
    assert predict_label("impositive", LABELS)[0] is None


# ------------------------------------------------------------------ 5.4 aggregates (hand computed)
def test_classification_metrics_hand_computed():
    pairs = [
        ("cat", "cat"),
        ("cat", "cat"),
        ("cat", "dog"),  # cat: tp2 fn1
        ("dog", "dog"),
        ("dog", "cat"),  # dog: tp1 fn1 ; cat fp1
        ("dog", None),  # dog: fn+1, unparseable
    ]
    m = classification_metrics(pairs)
    assert m["n"] == 6 and m["accuracy"] == pytest.approx(3 / 6)
    assert m["unparseable"] == 1
    cat, dog = m["per_label"]["cat"], m["per_label"]["dog"]
    assert cat["precision"] == pytest.approx(2 / 3)  # tp2 / (tp2 + fp1)
    assert cat["recall"] == pytest.approx(2 / 3)  # tp2 / (tp2 + fn1)
    assert dog["precision"] == pytest.approx(1 / 2)  # tp1 / (tp1 + fp1)
    assert dog["recall"] == pytest.approx(1 / 3)  # tp1 / (tp1 + fn2)
    assert cat["support"] == 3 and dog["support"] == 3
    assert m["confusion"]["rows"]["cat"] == {"cat": 2, "dog": 1, "unparseable": 0}
    assert m["confusion"]["rows"]["dog"] == {"cat": 1, "dog": 1, "unparseable": 1}


def test_classification_metrics_empty_and_single_label():
    assert classification_metrics([])["accuracy"] is None
    assert classification_metrics([("a", "a")])["confusion"] is None


# ------------------------------------------------------------------ 5.5 reasoning
@pytest.mark.parametrize(
    "text,final,method",
    [
        ("... so\nFinal answer: 42", "42", "marker"),
        ("Final answer: <5>", "5", "marker"),
        ("**Final answer:** $1,234.50.", "1,234.50", "marker"),
        ("Final answer:\n\n  270 km", "270 km", "marker"),
        ("First final answer: 1\nFinal answer: 2", "2", "marker"),
        ("so \\boxed{7}", "7", "boxed"),
        ("Therefore the answer is 9.", "9", "answer_is"),
        ("It is 12 apples", "It is 12 apples", "fallback"),
        ("", None, "none"),
    ],
)
def test_extract_final_answer(text, final, method):
    assert extract_final_answer(text) == (final, method)


def test_numeric_marked_answer_exact():
    r = score_reasoning("Final answer: 42", "42", "numeric", 0)
    assert (r.value, r.outcome) == (1.0, "correct") and r.detail["method"] == "marker"


def test_numeric_tolerance():
    assert score_reasoning("Final answer: 3.14", "3.1416", "numeric", 0.01).outcome == "correct"
    assert score_reasoning("Final answer: 3.2", "3.1416", "numeric", 0.01).outcome == "wrong"
    assert score_reasoning("Final answer: 3.14", "3.1416", "numeric", 0).outcome == "wrong"


def test_numeric_formats():
    assert score_reasoning("Final answer: $1,234", "1234", "numeric").outcome == "correct"
    assert score_reasoning("Final answer: 270 km", "270", "numeric").outcome == "correct"
    assert score_reasoning("Final answer: 1/2", "0.5", "numeric").outcome == "correct"


def test_numeric_fallback_uses_last_number():
    r = score_reasoning("60*2.5=150 and 80*1.5=120 so 270 total", "270", "numeric")
    assert r.outcome == "correct" and r.detail["method"] == "last_number"


def test_unparseable_when_no_number_or_empty():
    assert score_reasoning("Final answer: cannot be determined", "4", "numeric").outcome == "unparseable"
    assert score_reasoning("no digits here", "4", "numeric").outcome == "unparseable"
    r = score_reasoning("", "4", "numeric")
    assert (r.value, r.outcome) == (0.0, "unparseable")


def test_text_comparison():
    assert score_reasoning("Final answer: Yes", "yes").outcome == "correct"
    assert score_reasoning("Final answer: no", "yes").outcome == "wrong"
    assert score_reasoning("Yes, because of transitivity", "yes").outcome == "correct"  # fallback prefix rule
    assert score_reasoning("Final answer: Yes, indeed", "yes").outcome == "wrong"  # marked answers are strict


def test_no_expected_is_unscored():
    r = score_reasoning("Final answer: 4", None, "numeric")
    assert r.value is None and r.outcome == "unscored" and r.detail["parsed"] == 4
