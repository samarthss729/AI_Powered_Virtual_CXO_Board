"""Isolated OpenAI LLM integration with optional DEMO_MODE bypass."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import APIError, OpenAI, RateLimitError

from app.core.config import get_settings
from app.services.demo_responses import mock_chat, mock_chat_json


logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """Raised when the LLM call fails in a user-visible way."""


class AIService:
    """Thin wrapper around the OpenAI Chat Completions API.

    When ``DEMO_MODE=true`` in backend configuration, this service returns
    deterministic mock executive responses and never initializes the OpenAI client.
    """

    def __init__(self, client: OpenAI | None = None) -> None:
        self.settings = get_settings()
        self._client = client

    @property
    def client(self) -> OpenAI:
        """Create the OpenAI client lazily when it is first needed."""
        if self.settings.demo_mode:
            raise AIServiceError(
                "OpenAI client is unavailable while DEMO_MODE=true."
            )
        if self._client is None:
            api_key = self.settings.require_openai_key()
            self._client = OpenAI(api_key=api_key)

        return self._client

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.6,
        max_tokens: int = 700,
    ) -> str:
        """Send a chat request to OpenAI and return the text response."""

        # DEMO_MODE bypasses OpenAI entirely with persona-aware mock responses.
        if self.settings.demo_mode:
            return mock_chat(system_prompt=system_prompt, user_prompt=user_prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
            )

        except ValueError as exc:
            logger.exception("OpenAI configuration/value error")
            raise AIServiceError(str(exc)) from exc

        except RateLimitError as exc:
            # Log the real OpenAI error so we can diagnose whether this
            # is a rate limit, quota, billing, or another 429 condition.
            logger.exception("OpenAI RateLimitError: %s", exc)

            raise AIServiceError(
                f"OpenAI API rate/quota error: {exc}"
            ) from exc

        except APIError as exc:
            # Log the complete API error for debugging.
            logger.exception("OpenAI APIError: %s", exc)

            raise AIServiceError(
                f"OpenAI API error: {exc}"
            ) from exc

        except Exception as exc:
            # Catch unexpected errors and log the full traceback.
            logger.exception("Unexpected LLM failure")

            raise AIServiceError(
                f"Failed to reach the language model: {exc}"
            ) from exc

        content = (
            response.choices[0].message.content
            if response.choices
            else None
        )

        if not content:
            raise AIServiceError(
                "The language model returned an empty response."
            )

        return content.strip()

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        """Send a request and parse the response as JSON."""

        # DEMO_MODE returns the same synthesis schema without calling OpenAI.
        if self.settings.demo_mode:
            return mock_chat_json(system_prompt=system_prompt, user_prompt=user_prompt)

        raw = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse JSON returned by the model."""

        text = raw.strip()

        # Remove Markdown code fences such as:
        #
        # ```json
        # {...}
        # ```
        if text.startswith("```"):
            lines = text.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)

        except json.JSONDecodeError as exc:
            # Sometimes the model adds a little text before/after the JSON.
            # Try extracting the outermost JSON object.
            start = text.find("{")
            end = text.rfind("}")

            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start : end + 1])

                except json.JSONDecodeError as inner:
                    raise AIServiceError(
                        "Board synthesis returned invalid JSON."
                    ) from inner

            else:
                raise AIServiceError(
                    "Board synthesis returned invalid JSON."
                ) from exc

        if not isinstance(data, dict):
            raise AIServiceError(
                "Board synthesis JSON must be an object."
            )

        return data
