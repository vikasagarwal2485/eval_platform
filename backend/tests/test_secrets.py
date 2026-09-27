"""1.3: key lookup at call time, env-name validation, redaction, provider settings."""

import pytest

from app.config import load_settings
from app.providers.secrets import MARK, KeyProvider, Redactor, valid_env_name

KEY = "sk-proj-AbCdEf0123456789XyZqrstuvw"


def redactor(*secrets):
    return Redactor(lambda: list(secrets))


# ---------------------------------------------------------------- key lookup
def test_key_is_read_at_call_time_not_cached():
    env = {}
    kp = KeyProvider(env)
    assert kp.get("OPENAI_API_KEY") is None and not kp.available("OPENAI_API_KEY")
    env["OPENAI_API_KEY"] = KEY  # exported after the provider object was built
    assert kp.get("OPENAI_API_KEY") == KEY and kp.available("OPENAI_API_KEY")
    env["OPENAI_API_KEY"] = "rotated"
    assert kp.get("OPENAI_API_KEY") == "rotated"


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_empty_or_blank_counts_as_not_set(value):
    assert KeyProvider({"K": value}).get("K") is None
    assert not KeyProvider({"K": value}).available("K")


def test_default_provider_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("EVAL_TEST_KEY", "abc")
    assert KeyProvider().available("EVAL_TEST_KEY")
    monkeypatch.delenv("EVAL_TEST_KEY")
    assert not KeyProvider().available("EVAL_TEST_KEY")
    assert KeyProvider().get(None) is None


# ---------------------------------------------------------------- env name validation
@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MY_KEY_2", "_X", "A"])
def test_valid_env_names(name):
    assert valid_env_name(name) == (True, "")


@pytest.mark.parametrize(
    "bad,fragment",
    [
        ("", "must not be empty"),
        ("sk-proj-abc123", "looks like an API key"),
        ("sk-ant-api03-xyz", "looks like an API key"),
        ("AIzaSyD-example", "looks like an API key"),
        ("my key", "looks like an API key"),
        ("KEY=value", "looks like an API key"),
        ("lowercase_name", "upper-case"),
        ("1STARTS_WITH_DIGIT", "upper-case"),
        ("A" * 65, "looks like an API key"),
    ],
)
def test_key_shaped_or_invalid_names_are_rejected_with_a_reason(bad, fragment):
    ok, reason = valid_env_name(bad)
    assert not ok and fragment in reason


# ---------------------------------------------------------------- redaction
def test_full_value_is_removed_anywhere():
    r = redactor(KEY)
    assert r.redact(f"Bad key {KEY}, try again") == f"Bad key {MARK}, try again"
    assert KEY not in r.redact(f'{{"error": {{"message": "invalid: {KEY}"}}}}')
    assert r.redact(f"{KEY} and {KEY}").count(MARK) == 2


def test_partial_and_masked_echoes_are_removed():
    r = redactor(KEY)
    assert "AbCdEf0123456789" not in r.redact("Incorrect API key provided: sk-proj-AbCdEf0123456789***. See docs.")
    assert "0123456789XyZ" not in r.redact("...key ending in 0123456789XyZqrstuvw is invalid")
    out = r.redact("prefix AbCdEf0123456789XyZ suffix")  # a long stretch of the secret, not all of it
    assert "AbCdEf01234" not in out and out.startswith("prefix") and out.endswith("suffix")


def test_generic_key_shapes_are_removed_even_for_unknown_keys():
    r = redactor()
    assert r.redact("key sk-ant-api03-Zz9Yy8Xx7Ww6 rejected") == f"key {MARK} rejected"
    assert "sk-abcdefgh12345678" not in r.redact("used sk-abcdefgh12345678")
    assert r.redact("Authorization: Bearer abcdef1234567890xyz") == f"Authorization: Bearer {MARK}"
    assert "secretvalue123" not in r.redact('x-api-key: "secretvalue123"')
    assert "secretvalue123" not in r.redact("api_key=secretvalue123&x=1")


def test_several_secrets_and_longest_first():
    r = redactor("short-secret-1", "short-secret-1-and-longer-suffix")
    assert r.redact("a short-secret-1-and-longer-suffix b") == f"a {MARK} b"
    assert r.redact("x short-secret-1 y") == f"x {MARK} y"


def test_unrelated_text_is_untouched_and_idempotent():
    r = redactor(KEY)
    text = "Rate limit reached for gpt-4o in organization org-123 on tokens per min (TPM): Limit 30000"
    assert r.redact(text) == text
    once = r.redact(f"bad {KEY}")
    assert r.redact(once) == once


def test_short_secrets_only_match_in_full():
    r = redactor("abc123")
    assert r.redact("abc123 and abc") == f"{MARK} and abc"


def test_redact_exception_text_and_empty_inputs():
    r = redactor(KEY)
    assert r.redact_exc(RuntimeError(f"boom {KEY}")) == f"boom {MARK}"
    assert r.redact(None) == "" and r.redact("") == ""


def test_secrets_are_read_lazily_each_time():
    bag = []
    r = Redactor(lambda: bag)
    assert r.redact("token TOPSECRETVALUE1") == "token TOPSECRETVALUE1"
    bag.append("TOPSECRETVALUE1")  # a key registered later is still covered
    assert r.redact("token TOPSECRETVALUE1") == f"token {MARK}"


# ---------------------------------------------------------------- settings
def test_provider_settings_defaults_and_overrides():
    s = load_settings({})
    assert (s.provider_max_retries, s.provider_backoff_s, s.provider_backoff_cap_s) == (4, 1.0, 30.0)
    s = load_settings({"EVAL_PROVIDER_MAX_RETRIES": "2", "EVAL_PROVIDER_BACKOFF_S": "0.5"})
    assert (s.provider_max_retries, s.provider_backoff_s) == (2, 0.5)


def test_auth_header_echo_never_leaves_the_token_behind():
    r = redactor()
    for text in [
        "Authorization: Bearer tok_abcdef123456",
        "authorization=tok_abcdef123456",
        '"x-api-key": "tok_abcdef123456"',
    ]:
        assert "tok_abcdef123456" not in r.redact(text), text
