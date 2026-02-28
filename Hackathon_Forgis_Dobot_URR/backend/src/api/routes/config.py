from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ai_service import ai_service

router = APIRouter(prefix="/api/config", tags=["config"])

class ConfigUpdate(BaseModel):
    gemini_api_key: str

@router.post("/gemini")
async def update_gemini_config(config: ConfigUpdate):
    """Update Gemini API configuration at runtime."""
    print(f"DEBUG: Received config update request with key: {config.gemini_api_key[:5]}...")
    try:
        ai_service.configure(config.gemini_api_key)
        print("DEBUG: Gemini AI configured successfully")
        return {"status": "success", "message": "Gemini API key updated"}
    except Exception as e:
        print(f"DEBUG: Error configuring Gemini AI: {e}")
        raise HTTPException(status_code=500, detail=str(e))
