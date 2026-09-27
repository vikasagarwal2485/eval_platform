from app.core.tokens import display_prefix, generate_token, hash_token, verify_token


def test_generate_token_is_url_safe_and_unique():
    a, b = generate_token(), generate_token()
    assert a != b
    assert all(c.isalnum() or c in "-_" for c in a)


def test_hash_is_stable_and_verifiable():
    raw = generate_token()
    h = hash_token(raw)
    assert verify_token(raw, h)
    assert not verify_token(raw + "x", h)
    assert not verify_token(None, h)


def test_display_prefix_is_short_and_does_not_leak_full_token():
    raw = generate_token()
    prefix = display_prefix(raw)
    assert len(prefix) == 8
    assert raw.startswith(prefix)
    assert prefix != raw
