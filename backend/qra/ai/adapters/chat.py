"""Chat adapters (WP-09, WP-13).

Six wire protocols cover sixteen providers, because most of the industry speaks
OpenAI's shape. Each adapter does three things and no more: send the call,
normalise the response into :class:`ChatResult`, and translate failure into
:class:`ProviderUnavailable`.

Structured output is per-spec, not per-call-site:

* ``native``    — the provider enforces the schema (tool-use / json_schema).
* ``json_mode`` — the provider guarantees syntactic JSON but not the shape.
* ``none``      — we ask in the prompt and parse what comes back.

The distinction matters because the caller must know whether a returned object
was *validated* or merely *parsed*, and :class:`ChatResult` carries that.
"""

from __future__ import annotations

import json
from typing import Any

from qra.ai.adapters._http import (
    DEFAULT_TIMEOUT,
    LOCAL_TIMEOUT,
    json_from_text,
    post,
    require_key,
)
from qra.ai.base import ChatResult, ProviderRefusal, ProviderUnavailable
from qra.ai.registry import ModelSpec

SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object and nothing else — no prose, no code fence. "
    "It must match this JSON Schema:\n{schema}"
)


def _schema_prompt(user: str, schema: dict) -> str:
    return f"{user}\n\n{SCHEMA_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))}"


class _Base:
    """Shared adapter state. Subclasses implement :meth:`chat` only."""

    def __init__(self, spec: ModelSpec, *, api_key: str | None = None, base_url: str | None = None):
        self.spec = spec
        self.api_key = api_key
        self.base_url = (base_url or spec.base_url or "").rstrip("/")
        self.timeout = LOCAL_TIMEOUT if spec.local else DEFAULT_TIMEOUT

    @property
    def name(self) -> str:
        return f"{self.spec.provider}/{self.spec.id}"

    def _key(self) -> str:
        return require_key(self.spec, self.api_key)

    def _result(self, text: str, *, tokens_in: int, tokens_out: int, finish: str, raw: dict,
                schema: dict | None, validated: bool) -> ChatResult:
        structured = None
        if schema is not None:
            try:
                structured = json.loads(text) if validated else json_from_text(text)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProviderUnavailable(
                    f"{self.name} was asked for JSON and returned prose: {exc}",
                    reason="unavailable",
                    provider=self.spec.provider,
                ) from exc
        return ChatResult(
            text=text,
            model=self.spec.id,
            provider=self.spec.provider,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            finish_reason=finish,
            structured=structured,
            raw={**raw, "schema_enforced": bool(schema) and validated},
        )


class AnthropicChat(_Base):
    """Native structured output via a forced tool call."""

    def chat(self, *, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0, schema: dict | None = None) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.spec.id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        native = schema is not None and self.spec.structured_output == "native"
        if native:
            body["tools"] = [{
                "name": "emit",
                "description": "Return the answer in the required shape.",
                "input_schema": schema,
            }]
            body["tool_choice"] = {"type": "tool", "name": "emit"}
        elif schema is not None:
            body["messages"][0]["content"] = _schema_prompt(user, schema)

        payload = post(
            f"{self.base_url or 'https://api.anthropic.com'}/v1/messages",
            provider=self.spec.provider,
            headers={
                "x-api-key": self._key(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json_body=body,
            timeout=self.timeout,
        )
        blocks = payload.get("content", [])
        if native:
            for block in blocks:
                if block.get("type") == "tool_use":
                    text = json.dumps(block.get("input", {}), ensure_ascii=False)
                    break
            else:
                raise ProviderRefusal(
                    f"{self.name} declined the structured call",
                    provider=self.spec.provider,
                )
        else:
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = payload.get("usage", {})
        return self._result(
            text,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            finish=payload.get("stop_reason", "stop"),
            raw={"id": payload.get("id")},
            schema=schema,
            validated=native,
        )


class OpenAIChat(_Base):
    """Covers openai, mistral, deepseek, groq, xai, together, fireworks,
    openrouter, vllm and llama.cpp — anything speaking ``/chat/completions``."""

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._key()
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def chat(self, *, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0, schema: dict | None = None) -> ChatResult:
        mode = self.spec.structured_output
        body: dict[str, Any] = {
            "model": self.spec.id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        validated = False
        if schema is not None:
            if mode == "native":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema, "strict": False},
                }
                validated = True
            elif mode == "json_mode":
                body["response_format"] = {"type": "json_object"}
                body["messages"][1]["content"] = _schema_prompt(user, schema)
            else:
                body["messages"][1]["content"] = _schema_prompt(user, schema)

        payload = post(self._url(), provider=self.spec.provider, headers=self._headers(),
                       json_body=body, timeout=self.timeout)
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderUnavailable(
                f"{self.name} returned no choices", reason="unavailable", provider=self.spec.provider
            )
        message = choices[0].get("message", {})
        text = message.get("content") or ""
        finish = choices[0].get("finish_reason", "stop")
        if finish == "content_filter":
            raise ProviderRefusal(f"{self.name} filtered the response", provider=self.spec.provider)
        usage = payload.get("usage", {})
        return self._result(
            text,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            finish=finish,
            raw={"id": payload.get("id")},
            schema=schema,
            validated=validated,
        )


class AzureOpenAIChat(OpenAIChat):
    """Same wire shape, different auth header and a deployment-scoped URL.

    ``base_url`` must be the full deployment path; there is no sensible default
    because the resource name is per-tenant.
    """

    API_VERSION = "2024-10-21"

    def _url(self) -> str:
        if not self.base_url:
            raise ProviderUnavailable(
                "azure_openai needs a deployment base_url "
                "(https://<resource>.openai.azure.com/openai/deployments/<deployment>)",
                reason="no_credential",
                provider=self.spec.provider,
            )
        return f"{self.base_url}/chat/completions?api-version={self.API_VERSION}"

    def _headers(self) -> dict[str, str]:
        return {"content-type": "application/json", "api-key": self._key()}


class GoogleChat(_Base):
    """Gemini's ``generateContent``. System prompt is a separate field."""

    def _endpoint(self) -> str:
        base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"
        return f"{base}/models/{self.spec.id}:generateContent"

    def _auth_headers(self) -> dict[str, str]:
        return {"content-type": "application/json", "x-goog-api-key": self._key()}

    def chat(self, *, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0, schema: dict | None = None) -> ChatResult:
        config: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        validated = False
        if schema is not None:
            if self.spec.structured_output == "native":
                config["responseMimeType"] = "application/json"
                config["responseSchema"] = _to_gemini_schema(schema)
                validated = True
            else:
                user = _schema_prompt(user, schema)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        payload = post(
            self._endpoint(),
            provider=self.spec.provider,
            headers=self._auth_headers(),
            json_body=body,
            timeout=self.timeout,
        )
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ProviderRefusal(
                f"{self.name} returned no candidates "
                f"({payload.get('promptFeedback', {}).get('blockReason', 'no reason given')})",
                provider=self.spec.provider,
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage = payload.get("usageMetadata", {})
        return self._result(
            text,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            finish=candidates[0].get("finishReason", "stop"),
            raw={},
            schema=schema,
            validated=validated,
        )


def _to_gemini_schema(schema: dict) -> dict:
    """Gemini takes an OpenAPI subset: uppercase types, no ``additionalProperties``."""
    drop = {"additionalProperties", "$schema", "definitions", "$defs"}
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in drop:
            continue
        if key == "type" and isinstance(value, str):
            out["type"] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {k: _to_gemini_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            out["items"] = _to_gemini_schema(value)
        else:
            out[key] = value
    return out


class OllamaChat(_Base):
    """The local tier. No key, a long timeout, and ``format`` for JSON."""

    def chat(self, *, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0, schema: dict | None = None) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.spec.id,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if schema is not None:
            # Recent Ollama accepts a schema here; older builds accept "json".
            body["format"] = schema if self.spec.structured_output == "native" else "json"
            body["messages"][1]["content"] = _schema_prompt(user, schema)
        payload = post(
            f"{self.base_url or 'http://localhost:11434'}/api/chat",
            provider=self.spec.provider,
            json_body=body,
            timeout=self.timeout,
        )
        text = payload.get("message", {}).get("content", "")
        return self._result(
            text,
            tokens_in=payload.get("prompt_eval_count", 0),
            tokens_out=payload.get("eval_count", 0),
            finish=payload.get("done_reason", "stop"),
            raw={},
            schema=schema,
            validated=False,
        )


class BedrockChat(_Base):
    """AWS Bedrock via boto3 Converse. SigV4 is not worth hand-rolling."""

    def chat(self, *, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0, schema: dict | None = None) -> ChatResult:
        try:
            import boto3  # noqa: PLC0415
            from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                "bedrock needs boto3 (pip install boto3)",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        region = self.spec.extra.get("region", "us-east-1")
        if schema is not None:
            user = _schema_prompt(user, schema)
        try:
            client = boto3.client("bedrock-runtime", region_name=region)
            payload = client.converse(
                modelId=self.spec.id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
        except (BotoCoreError, ClientError) as exc:
            name = type(exc).__name__
            reason = "rate_limit" if "Throttl" in name else "unavailable"
            raise ProviderUnavailable(
                f"bedrock call failed: {exc}", reason=reason, provider=self.spec.provider
            ) from exc
        blocks = payload.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks)
        usage = payload.get("usage", {})
        return self._result(
            text,
            tokens_in=usage.get("inputTokens", 0),
            tokens_out=usage.get("outputTokens", 0),
            finish=payload.get("stopReason", "stop"),
            raw={},
            schema=schema,
            validated=False,
        )


class VertexChat(GoogleChat):
    """Vertex speaks the Gemini shape behind an OAuth token from ADC.

    Project and location come from config (``project:`` / ``location:`` in the
    provider block) or the usual Google env vars — never from a hardcoded
    default, which would silently bill the wrong account.
    """

    def _endpoint(self) -> str:
        import os

        project = self.spec.extra.get("project") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = (
            self.spec.extra.get("location")
            or os.environ.get("GOOGLE_CLOUD_LOCATION")
            or "us-central1"
        )
        if not project:
            raise ProviderUnavailable(
                "vertex needs a project (set GOOGLE_CLOUD_PROJECT or `project:` in models.yaml)",
                reason="no_credential",
                provider=self.spec.provider,
            )
        base = self.base_url or f"https://{location}-aiplatform.googleapis.com/v1"
        return (
            f"{base}/projects/{project}/locations/{location}"
            f"/publishers/google/models/{self.spec.id}:generateContent"
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"content-type": "application/json", "authorization": f"Bearer {self._key()}"}

    def _key(self) -> str:
        try:
            import google.auth  # noqa: PLC0415
            from google.auth.transport.requests import Request  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                "vertex needs google-auth (pip install google-auth)",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        try:
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001 - any ADC failure is "no credential"
            raise ProviderUnavailable(
                f"vertex credentials unavailable: {exc}",
                reason="no_credential",
                provider=self.spec.provider,
            ) from exc
        return creds.token


CHAT_ADAPTERS: dict[str, type[_Base]] = {
    "anthropic": AnthropicChat,
    "openai": OpenAIChat,
    "azure": AzureOpenAIChat,
    "google": GoogleChat,
    "ollama": OllamaChat,
    "bedrock": BedrockChat,
    "vertex": VertexChat,
}
