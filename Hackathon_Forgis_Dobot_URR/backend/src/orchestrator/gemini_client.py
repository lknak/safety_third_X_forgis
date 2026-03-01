"""Gemini client adapters for orchestrator, ER, and live commentary."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import google.generativeai as genai
from PIL import Image
import io

logger = logging.getLogger(__name__)

DEFAULT_ORCHESTRATOR_MODEL = "gemini-2.5-flash"
DEFAULT_ER_MODEL = "gemini-robotics-er-1.5-preview"
# Live commentary currently uses generateContent in this service path.
DEFAULT_LIVE_MODEL = "gemini-2.5-flash"


class GeminiClientError(RuntimeError):
    """Raised when Gemini is not configured or returns invalid payloads."""


class OrchestratorGeminiClient:
    """Thin async wrapper over google-generativeai models."""

    def __init__(self):
        self._api_key: Optional[str] = None
        self._text_model = None
        self._er_model = None
        self._live_model = None

    @property
    def orchestrator_model(self) -> str:
        return os.environ.get("GEMINI_ORCHESTRATOR_MODEL", DEFAULT_ORCHESTRATOR_MODEL)

    @property
    def er_model(self) -> str:
        return os.environ.get("GEMINI_ER_MODEL", DEFAULT_ER_MODEL)

    @property
    def live_model(self) -> str:
        return os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_LIVE_MODEL)

    def _ensure_models(self) -> None:
        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            raise GeminiClientError("GEMINI_API_KEY is not configured")

        if self._text_model is not None and self._api_key == api_key:
            return

        genai.configure(api_key=api_key)
        self._api_key = api_key
        self._text_model = genai.GenerativeModel(self.orchestrator_model)
        self._er_model = genai.GenerativeModel(self.er_model)
        self._live_model = genai.GenerativeModel(self.live_model)

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        return ""

    async def health_check(self) -> tuple[bool, str]:
        """Validate API key and configured orchestrator model connectivity."""
        prompt = "Reply with exactly OK"
        try:
            text = await self.generate_text(prompt, model=self.orchestrator_model)
        except Exception as exc:
            return False, str(exc)

        if "OK" not in text.upper():
            return False, f"Unexpected health response: {text[:120]}"

        return True, "OK"

    async def generate_text(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate text content using Gemini."""
        self._ensure_models()
        target_model = model or self.orchestrator_model
        llm = genai.GenerativeModel(target_model)
        response = await llm.generate_content_async(prompt)
        text = self._extract_text(response)
        if not text:
            raise GeminiClientError("Gemini returned an empty response")
        return text

    async def generate_json(self, prompt: str, model: Optional[str] = None) -> dict[str, Any]:
        """Generate and parse JSON object from Gemini response."""
        text = await self.generate_text(prompt, model=model)
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            return json.loads(cleaned)
        except Exception as exc:
            raise GeminiClientError(f"Failed to parse JSON response: {exc}; body={cleaned[:200]}") from exc

    async def analyze_er(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
    ) -> dict[str, Any]:
        """Analyze perception/planning prompt using ER model."""
        self._ensure_models()
        llm = genai.GenerativeModel(self.er_model)

        if image_bytes:
            image = Image.open(io.BytesIO(image_bytes))
            response = await llm.generate_content_async([prompt, image])
        else:
            response = await llm.generate_content_async(prompt)

        text = self._extract_text(response)
        if not text:
            raise GeminiClientError("Gemini ER returned empty response")

        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Fallback: find the outermost JSON object or array in the response
        for start_char, end_char in (('{', '}'), ('[', ']')):
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end > start:
                candidate = cleaned[start:end + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    pass

        raise GeminiClientError(f"Gemini ER returned non-JSON payload: {cleaned[:200]}")

    async def er_trajectory(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
    ) -> list[dict[str, Any]]:
        """Plan a trajectory using Gemini ER.  Returns a JSON array of waypoints.

        Each waypoint: {"point": [y, x], "label": "<order>"}
        Coordinates are normalised to 0-1000.
        """
        self._ensure_models()
        llm = genai.GenerativeModel(self.er_model)

        parts: list[Any] = []
        if image_bytes:
            parts.append(Image.open(io.BytesIO(image_bytes)))
        parts.append(prompt)

        response = await llm.generate_content_async(
            parts,
            generation_config=genai.types.GenerationConfig(temperature=0.5),
        )

        text = self._extract_text(response)
        if not text:
            raise GeminiClientError("Gemini ER returned empty trajectory response")

        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(cleaned)
        except Exception as exc:
            raise GeminiClientError(
                f"Gemini ER returned non-JSON trajectory: {cleaned[:200]}"
            ) from exc

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # ER sometimes wraps array in {"trajectory": [...]}
            for key in ("trajectory", "points", "waypoints"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return [data]

    async def live_commentary(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
    ) -> str:
        """Generate a short live commentary snippet.

        If image_bytes are supplied, attempt multimodal live commentary first.
        Falls back to text-only live commentary if the model path rejects image input.
        """
        self._ensure_models()
        try:
            if image_bytes:
                image = Image.open(io.BytesIO(image_bytes))
                response = await self._live_model.generate_content_async([prompt, image])
            else:
                response = await self._live_model.generate_content_async(prompt)
            text = self._extract_text(response)
            if text:
                return text
        except Exception as exc:
            if image_bytes:
                logger.warning(
                    "Live model image commentary failed, retrying text-only: %s",
                    exc,
                )
                response = await self._live_model.generate_content_async(prompt)
                text = self._extract_text(response)
                if text:
                    return text
            else:
                raise

        raise GeminiClientError("Gemini live commentary returned empty response")
