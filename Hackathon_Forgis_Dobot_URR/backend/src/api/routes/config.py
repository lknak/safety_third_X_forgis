import logging
import os

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from ai_service import ai_service

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger(__name__)

class ConfigUpdate(BaseModel):
    gemini_api_key: str | None = None
    api_key: str | None = None

    def resolved_api_key(self) -> str:
        # Accept both modern and legacy payload names.
        return (self.gemini_api_key or self.api_key or "").strip()

@router.post("/gemini")
async def update_gemini_config(config: ConfigUpdate):
    """Update Gemini API configuration at runtime."""
    api_key = config.resolved_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gemini API key must not be empty.",
        )

    try:
        ai_service.configure(api_key)
        os.environ["GEMINI_API_KEY"] = api_key
        logger.info("Gemini API key updated at runtime")
        return {"status": "success", "message": "Gemini API key updated"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as e:
        logger.exception("Failed to configure Gemini API key")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to configure Gemini API key.",
        ) from e
