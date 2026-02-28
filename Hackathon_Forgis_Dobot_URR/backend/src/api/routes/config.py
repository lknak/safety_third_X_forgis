from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ai_service import ai_service

router = APIRouter(prefix="/api/config", tags=["config"])

class ConfigUpdate(BaseModel):
    gemini_api_key: str

@router.post("/gemini")
async def update_gemini_config(config: ConfigUpdate):
    """Update Gemini API configuration at runtime."""
    try:
        ai_service.configure(config.gemini_api_key)
        return {"status": "success", "message": "Gemini API key updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
