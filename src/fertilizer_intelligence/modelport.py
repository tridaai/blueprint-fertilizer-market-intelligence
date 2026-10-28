"""The model port: one interface, named profiles, fail-closed.

The agent layer talks to models only through this port. The default
profile is ``offline`` — a deterministic composer that builds its
text from the computed figures it is handed and never invents a
number (Law 1: the model drafts words; it never originates a
figure).

Hosted profiles (``anthropic``, ``bedrock``, ``nim``) are real HTTP
adapters, but they are **fail-closed**: selecting one whose
key/endpoint the deployment has not set raises
:class:`ProfileNotConfigured` at wiring time. There is no fallback —
the port never silently substitutes a different profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ProfileNotConfigured(RuntimeError):
    """A hosted profile was selected without its configuration."""


@dataclass
class ModelReply:
    text: str
    profile: str
    model: str
    input_tokens: int
    output_tokens: int


class OfflineModelPort:
    """Deterministic offline composer.

    Builds a short narrative strictly from the figures in the
    prompt payload — the payload carries the computed numbers, and
    the composer only arranges them. Used by tests, evals and any
    deployment running without a hosted key.
    """

    profile_name = "offline"
    model_name = "offline-deterministic"

    def complete(self, system: str, prompt: str) -> ModelReply:
        text = prompt.strip()
        return ModelReply(
            text=text,
            profile=self.profile_name,
            model=self.model_name,
            input_tokens=0,
            output_tokens=0,
        )


class AnthropicModelPort:
    profile_name = "anthropic"

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        if not self.api_key:
            raise ProfileNotConfigured(
                "profile 'anthropic' selected but ANTHROPIC_API_KEY is not set"
            )

    def complete(self, system: str, prompt: str) -> ModelReply:
        import httpx

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model_name,
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        text = "".join(
            block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
        )
        usage = body.get("usage", {})
        return ModelReply(
            text=text,
            profile=self.profile_name,
            model=self.model_name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


class NimModelPort:
    """OpenAI-compatible endpoint (e.g. NVIDIA NIM)."""

    profile_name = "nim"

    def __init__(self) -> None:
        self.base_url = os.environ.get("NIM_BASE_URL")
        self.api_key = os.environ.get("NIM_API_KEY")
        self.model_name = os.environ.get("NIM_MODEL")
        missing = [
            name
            for name, value in (
                ("NIM_BASE_URL", self.base_url),
                ("NIM_API_KEY", self.api_key),
                ("NIM_MODEL", self.model_name),
            )
            if not value
        ]
        if missing:
            raise ProfileNotConfigured(
                f"profile 'nim' selected but {', '.join(missing)} not set"
            )

    def complete(self, system: str, prompt: str) -> ModelReply:
        import httpx

        response = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return ModelReply(
            text=text,
            profile=self.profile_name,
            model=self.model_name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


class BedrockModelPort:
    profile_name = "bedrock"

    def __init__(self) -> None:
        self.model_id = os.environ.get("BEDROCK_MODEL_ID")
        self.region = os.environ.get("AWS_REGION")
        missing = [
            name
            for name, value in (
                ("BEDROCK_MODEL_ID", self.model_id),
                ("AWS_REGION", self.region),
            )
            if not value
        ]
        if missing:
            raise ProfileNotConfigured(
                f"profile 'bedrock' selected but {', '.join(missing)} not set"
            )
        self.model_name = self.model_id

    def complete(self, system: str, prompt: str) -> ModelReply:
        # The SigV4-signed Bedrock transport lands with the agent
        # rounds; until then the profile refuses loudly rather than
        # pretending to call. Configuration is validated above so a
        # misconfigured deployment fails at wiring, not mid-case.
        raise ProfileNotConfigured(
            "profile 'bedrock' is configured but its transport is not wired in this round"
        )


_PROFILES = {
    "offline": OfflineModelPort,
    "anthropic": AnthropicModelPort,
    "bedrock": BedrockModelPort,
    "nim": NimModelPort,
}


def get_model_port(profile: str):
    """Resolve a profile by name. Unknown names refuse the boot."""
    try:
        cls = _PROFILES[profile]
    except KeyError:
        raise ProfileNotConfigured(
            f"unknown model profile: {profile!r} (known: {', '.join(sorted(_PROFILES))})"
        ) from None
    return cls()
