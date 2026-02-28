from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from ai_service import ai_service
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cell", tags=["cell"])

class CellStateSummary(BaseModel):
    state: str
    active_objects: List[str]
    anomalies: List[str]
    safety_status: str
    confidence: float

@router.post("/infer-state", response_model=CellStateSummary)
async def infer_cell_state(
    image: UploadFile = File(...),
    context: Optional[str] = Form(None)
):
    """
    Infer the current state of the robot cell using Gemini Vision.
    """
    try:
        image_bytes = await image.read()
        
        prompt = f"""
        You are an industrial robotics supervisor. Analyze the provided image of a robot cell.
        Context: {context or 'General monitoring'}
        
        Provide a structured JSON summary of the current cell state with the following fields:
        1. state: A concise description of the current activity (e.g., 'Picking objects', 'Idle', 'Tool changing')
        2. active_objects: List of key objects identified in the workspace.
        3. anomalies: List of any potential issues or unexpected objects (empty if none).
        4. safety_status: One of ['Clear', 'Warning', 'Hazard']
        5. confidence: A float between 0 and 1 representing your certainty.
        
        Return ONLY the JSON object.
        """
        
        response_text = await ai_service.analyze_image(prompt, image_bytes)
        
        # Clean up response if it contains markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        try:
            state_data = json.loads(response_text)
            return CellStateSummary(**state_data)
        except Exception as json_err:
            logger.error(f"Failed to parse Gemini Vision response: {json_err}. Raw: {response_text}")
            # Fallback
            return CellStateSummary(
                state="Unknown (Analysis Error)",
                active_objects=[],
                anomalies=["Failed to parse AI response"],
                safety_status="Warning",
                confidence=0.0
            )
            
    except Exception as e:
        logger.error(f"Cell state inference failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
