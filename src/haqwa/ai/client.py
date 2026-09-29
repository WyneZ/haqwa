"""The single place Haqwa calls Gemini: structured JSON output, retries, disk cache.

`parse`, `clarify` and `explain` all go through `GeminiClient.generate`. The client
never decides pass/fail; it only returns Gemini's validated answer.

Quota (free tier, gemini-3.6-flash): 5 requests/minute and 20/day per project.
- 503 / network drop: retried with backoff (2s, 4s, 8s).
- 429 per minute: wait the delay Gemini asks for, retry up to twice.
- 429 per day: stop at once (retrying only burns more quota) -> GeminiQuotaError.
- Answers that validate are cached in `.haqwa_cache/`, so the same prompt costs quota once.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from google.genai import errors as genai_errors
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_CACHE_DIR = Path(".haqwa_cache")

SERVER_RETRY_DELAYS = (2.0, 4.0, 8.0)  # seconds; 3 retries after the first try
MINUTE_QUOTA_RETRIES = 2
MINUTE_QUOTA_FALLBACK_DELAY = 15.0  # used when Gemini gives no retryDelay
MAX_MINUTE_QUOTA_DELAY = 65.0  # never wait longer than about one minute


class GeminiError(Exception):
    """Base class for every error raised by the Gemini client."""


class GeminiQuotaError(GeminiError):
    """Free-tier quota is used up. Web maps this to HTTP 429 with code `gemini_quota`."""

    def __init__(self, message: str, *, per_day: bool) -> None:
        super().__init__(message)
        self.per_day = per_day


class GeminiUnavailable(GeminiError):
    """Gemini kept failing (5xx or network) after all retries."""


class GeminiBadOutput(GeminiError):
    """Gemini answered, but the JSON does not match the requested schema."""


@dataclass(frozen=True)
class GeminiResult[T: BaseModel]:
    """A validated Gemini answer. `cached` is True when no API call was made."""

    value: T
    cached: bool
    model: str


class GeminiClient:
    """Calls Gemini with a Pydantic response schema.

    Args:
        model: Gemini model id. Defaults to env `HAQWA_MODEL`, then `DEFAULT_MODEL`.
        cache_dir: Folder for cached answers. `None` turns the cache off.
        sdk: A `google.genai.Client` (or a fake in tests). Created lazily when omitted;
            the SDK reads the API key from the `GEMINI_API_KEY` environment variable.
        sleep: Wait function; tests pass a fake so they run instantly.
    """

    def __init__(
        self,
        model: str | None = None,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        sdk: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model or os.environ.get("HAQWA_MODEL") or DEFAULT_MODEL
        self.cache_dir = cache_dir
        self._sdk = sdk
        self._sleep = sleep

    def generate[T: BaseModel](self, prompt: str, schema: type[T]) -> GeminiResult[T]:
        """Return Gemini's answer to `prompt`, validated as `schema`.

        Raises:
            GeminiQuotaError: the daily quota is used up, or the per-minute limit persists.
            GeminiUnavailable: 5xx or network errors after all retries.
            GeminiBadOutput: the answer does not validate against `schema`.
        """
        key = self._cache_key(prompt, schema)
        cached = self._read_cache(key, schema)
        if cached is not None:
            return GeminiResult(value=cached, cached=True, model=self.model)

        text = self._call_with_retry(prompt, schema)
        try:
            value = schema.model_validate_json(text)
        except ValidationError as e:
            raise GeminiBadOutput(f"Gemini output does not match {schema.__name__}: {e}") from e

        self._write_cache(key, text)
        return GeminiResult(value=value, cached=False, model=self.model)

    # ---- Gemini call ---------------------------------------------------------------

    def _call_with_retry(self, prompt: str, schema: type[BaseModel]) -> str:
        server_retries = 0
        minute_retries = 0
        while True:
            try:
                response = self._client().models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": schema,
                        # We pass no tools, so automatic function calling is never needed.
                        # Turning it off also stops the SDK's "AFC is not recommended" warning.
                        "automatic_function_calling": {"disable": True},
                    },
                )
                return response.text or ""
            except genai_errors.ClientError as e:
                if e.code != 429:
                    raise
                if _is_per_day(e):
                    raise GeminiQuotaError(
                        "Gemini daily free-tier quota is used up. Try again after the daily reset.",
                        per_day=True,
                    ) from e
                if minute_retries >= MINUTE_QUOTA_RETRIES:
                    raise GeminiQuotaError(
                        "Gemini per-minute limit reached. Wait a minute and try again.",
                        per_day=False,
                    ) from e
                minute_retries += 1
                self._sleep(_retry_delay(e))
            except (genai_errors.ServerError, httpx.TransportError) as e:
                if server_retries >= len(SERVER_RETRY_DELAYS):
                    raise GeminiUnavailable(
                        f"Gemini is unavailable after {server_retries} retries: {e}"
                    ) from e
                self._sleep(SERVER_RETRY_DELAYS[server_retries])
                server_retries += 1

    def _client(self) -> Any:
        if self._sdk is None:
            from google import genai

            self._sdk = genai.Client()
        return self._sdk

    # ---- cache ---------------------------------------------------------------------

    def _cache_key(self, prompt: str, schema: type[BaseModel]) -> str:
        # Any change to model, prompt or schema gives a new key, so stale answers never match.
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "schema": schema.model_json_schema()},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _read_cache[T: BaseModel](self, key: str, schema: type[T]) -> T | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            return schema.model_validate_json(entry["response"])
        except (ValueError, KeyError, TypeError):
            return None  # corrupt or outdated entry: treat as a miss and overwrite it

    def _write_cache(self, key: str, text: str) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "model": self.model,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "response": text,
        }
        (self.cache_dir / f"{key}.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")


def _is_per_day(error: genai_errors.APIError) -> bool:
    # Gemini names the exhausted quota in `quotaId`, e.g.
    # "GenerateRequestsPerDayPerProjectPerModel-FreeTier" vs "...PerMinute...".
    return "PerDay" in json.dumps(error.details, default=str)


def _retry_delay(error: genai_errors.APIError) -> float:
    # RetryInfo carries e.g. "retryDelay": "34s".
    match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', json.dumps(error.details, default=str))
    delay = float(match.group(1)) if match else MINUTE_QUOTA_FALLBACK_DELAY
    return min(delay + 1.0, MAX_MINUTE_QUOTA_DELAY)
