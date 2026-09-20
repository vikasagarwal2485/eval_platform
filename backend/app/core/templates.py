"""Versioned per-category prompt templates.

A short instruction suffix is appended to the user's prompt so answers are machine-scorable.
The exact text sent and the template version are stored with every result.
"""

from __future__ import annotations

TEMPLATE_VERSION = "v1"

CLASSIFICATION_SUFFIX = "Respond with exactly one of these labels and nothing else: {labels}."
REASONING_SUFFIX = (
    "Think the problem through, then end your response with a final line of the form "
    "`Final answer: ` followed by only the answer itself (for example `Final answer: 42`)."
)


def suffix_for(category: str, config: dict | None) -> str:
    config = config or {}
    if category == "classification":
        return CLASSIFICATION_SUFFIX.format(labels=", ".join(config.get("labels", [])))
    if category == "reasoning":
        return REASONING_SUFFIX
    return ""  # generation: prompt is sent unchanged


def build_prompt(category: str, prompt: str, config: dict | None) -> tuple[str, str]:
    """Return (sent_prompt, template_version)."""
    suffix = suffix_for(category, config)
    sent = f"{prompt.rstrip()}\n\n{suffix}" if suffix else prompt
    return sent, TEMPLATE_VERSION


def build_messages(system_prompt: str | None, sent_prompt: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": sent_prompt})
    return msgs
