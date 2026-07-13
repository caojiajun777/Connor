from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LLMClientError(RuntimeError):
    pass


def _load_dotenv(*, override: bool = True) -> None:
    """Load KEY=VALUE pairs from project .env.

    By default, project .env overrides existing process env for local runs so a
    stale shell OPENAI_API_KEY cannot silently replace the DeepSeek key.
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


@dataclass
class LLMSettings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    timeout_sec: float = 600.0
    max_tokens: int = 65536
    reasoning_effort: str = "max"
    thinking_enabled: bool = True

    @classmethod
    def from_env(cls) -> LLMSettings:
        _load_dotenv()
        api_key = (
            os.environ.get("CONNOR_LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()
        if not api_key:
            raise LLMClientError(
                "Missing LLM API key. Set CONNOR_LLM_API_KEY or DEEPSEEK_API_KEY."
            )
        thinking_raw = os.environ.get("CONNOR_LLM_THINKING", "enabled").strip().lower()
        return cls(
            api_key=api_key,
            base_url=os.environ.get("CONNOR_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.environ.get("CONNOR_LLM_MODEL", "deepseek-v4-pro"),
            timeout_sec=float(os.environ.get("CONNOR_LLM_TIMEOUT_SEC", "600")),
            max_tokens=int(os.environ.get("CONNOR_LLM_MAX_TOKENS", "65536")),
            reasoning_effort=os.environ.get("CONNOR_LLM_REASONING_EFFORT", "max"),
            thinking_enabled=thinking_raw not in {"disabled", "0", "false", "off"},
        )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    candidates = [cleaned]
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    # Truncation salvage: close dangling braces/brackets from the end.
    repaired = cleaned.rstrip().rstrip(",")
    open_curly = repaired.count("{") - repaired.count("}")
    open_square = repaired.count("[") - repaired.count("]")
    if open_curly > 0 or open_square > 0:
        # Drop a trailing partial string / key if cut mid-token.
        repaired = re.sub(r',?\s*"[^"]*$', "", repaired)
        repaired = re.sub(r",\s*$", "", repaired)
        repaired += "]" * max(open_square, 0) + "}" * max(open_curly, 0)
        candidates.append(repaired)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(payload, dict):
            return payload
        last_error = LLMClientError("Model JSON root must be an object")
    raise LLMClientError(
        f"Model response did not contain valid JSON ({last_error})"
    ) from last_error


class OpenAICompatibleClient:
    """Minimal Chat Completions client with DeepSeek thinking-mode support."""

    def __init__(self, settings: LLMSettings | None = None):
        self.settings = settings or LLMSettings.from_env()
        self.last_reasoning_content: str | None = None
        self.last_raw_response: dict[str, Any] | None = None
        self.last_finish_reason: str | None = None

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        base = self.settings.base_url.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        body: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": 0.2,
            "max_tokens": self.settings.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.settings.thinking_enabled:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = self.settings.reasoning_effort
        else:
            body["thinking"] = {"type": "disabled"}

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_sec) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMClientError(f"LLM HTTP {exc.code}: {detail[:800]}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last_error = exc
                if attempt >= 3:
                    raise LLMClientError(f"LLM request failed after retries: {exc}") from exc
                import time

                time.sleep(2 * attempt)
        else:
            raise LLMClientError(f"LLM request failed: {last_error}")

        self.last_raw_response = payload
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected LLM response shape: {payload!r}") from exc

        self.last_reasoning_content = reasoning if isinstance(reasoning, str) else None
        self.last_finish_reason = finish_reason if isinstance(finish_reason, str) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM message content was empty")
        try:
            return _extract_json_object(content)
        except LLMClientError as exc:
            raise LLMClientError(
                f"{exc} (finish_reason={finish_reason!r}, content_chars={len(content)})"
            ) from exc
