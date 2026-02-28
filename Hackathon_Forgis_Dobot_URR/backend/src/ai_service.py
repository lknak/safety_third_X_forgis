"""AI Service for global LLM access (Gemini)."""

import logging
import os
from typing import Optional, Union, List, Dict, Any
import google.generativeai as genai
from PIL import Image
import io

logger = logging.getLogger(__name__)

class AIService:
    """
    Service for interacting with Gemini AI.
    Handles both text and vision tasks using a global API key.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            logger.info("Gemini AI configured with global API key from environment")
            
        self._text_model = genai.GenerativeModel("gemini-1.5-flash")
        self._vision_model = genai.GenerativeModel("gemini-1.5-flash")
        self._initialized = True

    def configure(self, api_key: str):
        """Configure Gemini AI with a new API key at runtime."""
        normalized_key = (api_key or "").strip()
        if not normalized_key:
            raise ValueError("Gemini API key must not be empty.")

        self.api_key = normalized_key
        genai.configure(api_key=self.api_key)
        # Re-initialize models with new config
        self._text_model = genai.GenerativeModel("gemini-1.5-flash")
        self._vision_model = genai.GenerativeModel("gemini-1.5-flash")
        logger.info("Gemini AI re-configured with new API key at runtime")

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate text from a prompt."""
        try:
            if not self.api_key:
                raise RuntimeError("Gemini API key is not configured.")

            model = self._text_model
            if system_instruction:
                model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_instruction)
            
            response = await model.generate_content_async(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini text generation error: {e}")
            return f"Error: {e}"

    async def analyze_image(self, prompt: str, image_bytes: bytes) -> str:
        """Analyze an image using Gemini Vision."""
        try:
            if not self.api_key:
                raise RuntimeError("Gemini API key is not configured.")

            image = Image.open(io.BytesIO(image_bytes))
            response = await self._vision_model.generate_content_async([prompt, image])
            return response.text
        except Exception as e:
            logger.error(f"Gemini image analysis error: {e}")
            return f"Error: {e}"

# Global instance
ai_service = AIService()
