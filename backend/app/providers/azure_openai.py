"""Azure OpenAI adapter (design D1/D3/D4): the chat-completions payload shape is the same as official OpenAI's, so
this subclasses `OpenAIBackend` and reuses its SSE parsing and `build_body()` unchanged, overriding only what Azure
does differently: an `api-key` header instead of a bearer token, a deployment-scoped request path with a mandatory
`api-version` query parameter, and no inference-plane endpoint to list deployments or ping provider-wide.
"""

from __future__ import annotations

from urllib.parse import quote

from app.providers.errors import ProviderError
from app.providers.openai import OpenAIBackend


class AzureOpenAIBackend(OpenAIBackend):
    kind = "azure-openai"
    default_base_url = ""  # always required at registration (design D2); never fall back to api.openai.com

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"api-key": key}

    @property
    def official(self) -> bool:
        """Azure is never the official OpenAI endpoint; `build_body` still picks `max_completion_tokens` for a
        reasoning-flagged deployment via the `reasoning` half of its `official or reasoning` check (design D5)."""
        return False

    def _chat_path(self, model: str) -> str:
        """`model` is the Azure deployment name; it goes in the URL, not the request body (design D3)."""
        deployment = quote(model, safe="")
        version = quote(self.cfg.api_version or "", safe="")
        return f"/openai/deployments/{deployment}/chat/completions?api-version={version}"

    async def list_models(self) -> list[str]:
        """No inference-plane endpoint lists deployments (that needs Azure Resource Manager + Azure AD, a different
        credential scheme entirely); the API layer never calls this for an azure-openai provider (design D9), but
        it fails clearly rather than hitting an OpenAI-shaped path that doesn't exist on an Azure resource."""
        raise ProviderError(
            "Azure OpenAI deployments cannot be listed automatically; add a deployment by name.",
            provider=self.cfg.name,
        )

    async def ping(self, model: str | None = None, reasoning: bool = False) -> None:
        """There is no provider-wide endpoint to ping (design D8): validate a specific deployment with a minimal
        chat completion instead. The caller (`test_provider`) only calls this once a deployment is registered.

        A reasoning deployment spends part of its token budget on hidden reasoning before any visible output, so a
        budget of 1 token (fine for an ordinary chat model) makes it fail with "max output limit reached" before it
        can answer at all - a false negative that looks like a broken connection. Reasoning deployments get a larger
        budget here for that reason alone; it does not change what a real run sends."""
        if not model:
            raise ProviderError("Azure OpenAI needs a registered deployment to test", provider=self.cfg.name)
        budget = 64 if reasoning else 1
        async for _ in self.chat_stream(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            options={"num_predict": budget},
            reasoning=reasoning,
        ):
            pass
