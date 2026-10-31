"""`app.core.secrets` (add-agent-playground, design.md D2)."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.secrets import PlaygroundSecretsDisabled, decrypt, encrypt


def test_round_trip():
    ciphertext = encrypt("super-secret-token", secret_key="a-passphrase")
    assert decrypt(ciphertext, secret_key="a-passphrase") == "super-secret-token"


def test_ciphertext_does_not_contain_plaintext():
    ciphertext = encrypt("super-secret-token", secret_key="a-passphrase")
    assert b"super-secret-token" not in ciphertext


def test_missing_key_raises_on_encrypt():
    with pytest.raises(PlaygroundSecretsDisabled):
        encrypt("x", secret_key=None)


def test_missing_key_raises_on_decrypt():
    with pytest.raises(PlaygroundSecretsDisabled):
        decrypt(b"whatever", secret_key=None)


def test_wrong_key_does_not_decrypt():
    ciphertext = encrypt("super-secret-token", secret_key="right-key")
    with pytest.raises(ValueError):
        decrypt(ciphertext, secret_key="wrong-key")


def test_decrypt_is_called_only_from_the_spawn_module():
    """`app.core.secrets.decrypt` must stay a spawn-only operation (design.md D2: 'never returned
    in plaintext by any read API'). Grep the app package for any other caller - the spawn module
    itself is the sole intended exception."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", r"secrets\.decrypt\(", str(app_dir)],
        capture_output=True,
        text=True,
    )
    callers = {
        line.split(":", 1)[0]
        for line in result.stdout.splitlines()
        if ":" in line and "def decrypt" not in line
    }
    allowed = {str(app_dir / "core" / "playground_spawn.py")}
    assert callers <= allowed, f"unexpected decrypt() callers: {callers - allowed}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
