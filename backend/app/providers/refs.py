"""Model references (design D2).

Ollama models are referenced by their bare name (`qwen3:8b`, `hf.co/org/model:tag`). Enterprise models are
referenced as `@<provider>/<model-id>`. A leading `@` can never start an Ollama name, so the two forms cannot
collide and every API field that carries a model name keeps working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROVIDER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_MODEL_ID = 200


@dataclass(frozen=True)
class ModelRef:
    provider: str | None  # None = Ollama
    model: str

    @property
    def is_cloud(self) -> bool:
        return self.provider is not None

    def __str__(self) -> str:
        return format_ref(self.provider, self.model)


def valid_provider_name(name: str) -> bool:
    return bool(PROVIDER_NAME_RE.match(name))


def format_ref(provider: str | None, model: str) -> str:
    if provider is None:
        return model
    return f"@{provider}/{model}"


def is_cloud_ref(ref: str) -> bool:
    return ref.startswith("@")


def parse_ref(ref: str) -> ModelRef:
    """Parse a reference. Raises ValueError for a malformed enterprise reference."""
    if not isinstance(ref, str) or not ref:
        raise ValueError("model reference must not be empty")
    if not ref.startswith("@"):
        return ModelRef(None, ref)
    provider, sep, model = ref[1:].partition("/")  # split at the first '/': model ids may contain '/' and ':'
    if not sep:
        raise ValueError(f"'{ref}' is not a valid model reference (expected @provider/model)")
    if not valid_provider_name(provider):
        raise ValueError(f"'{provider}' is not a valid provider name (lowercase letters, digits, '-' and '_')")
    if not model or model != model.strip() or len(model) > MAX_MODEL_ID:
        raise ValueError("model id must be non-empty, without surrounding spaces, and at most 200 characters")
    return ModelRef(provider, model)
