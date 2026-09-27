"""1.1: model references."""

import pytest

from app.providers.refs import ModelRef, format_ref, is_cloud_ref, parse_ref, valid_provider_name

OLLAMA_NAMES = [
    "qwen3:8b",
    "gemma4:e4b",
    "llama3",
    "hf.co/org/model:Q4_K_M",
    "library/llama3:latest",
    "registry.ollama.ai/library/x:1b",
    "openai:gpt-4o",  # looks provider-ish but is a legal Ollama name
    "anthropic/claude",
]


@pytest.mark.parametrize("name", OLLAMA_NAMES)
def test_bare_names_are_always_ollama(name):
    ref = parse_ref(name)
    assert ref == ModelRef(None, name) and not ref.is_cloud and not is_cloud_ref(name)
    assert str(ref) == name and format_ref(None, name) == name


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai-main", "gpt-4o"),
        ("anthropic", "claude-sonnet-4-20250514"),
        ("gateway", "openai/gpt-4o"),  # id containing '/'
        ("gw", "meta:llama-3.1-8b"),  # id containing ':'
        ("a", "x"),
        ("p_1-2", "model with.dots_and-dashes"),
    ],
)
def test_round_trip(provider, model):
    text = format_ref(provider, model)
    assert text == f"@{provider}/{model}" and is_cloud_ref(text)
    ref = parse_ref(text)
    assert ref == ModelRef(provider, model) and ref.is_cloud and str(ref) == text


def test_split_is_at_the_first_slash_after_the_at_sign():
    ref = parse_ref("@gw/org/team/model:v2")
    assert (ref.provider, ref.model) == ("gw", "org/team/model:v2")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "@",
        "@openai",
        "@/gpt-4o",
        "@OpenAI/gpt-4o",
        "@open ai/x",
        "@-x/y",
        "@a/",
        "@a/ x",
        "@a/x ",
        "@" + "p" * 41 + "/m",
        "@a/" + "m" * 201,
    ],
)
def test_malformed_references_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_ref(bad)


def test_provider_name_rule():
    assert all(valid_provider_name(n) for n in ["openai", "a", "team-1", "x_y", "0abc", "a" * 40])
    assert not any(valid_provider_name(n) for n in ["", "A", "-a", "_a", "a b", "a/b", "a@b", "a" * 41, "é"])
