from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional
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
    Cell diagnostics endpoint.

    AI-based diagnostics are currently disabled. The endpoint remains for
    backward compatibility with frontend callers and returns a static summary.
    """
    await image.read()
    logger.info("Cell diagnostics requested with context=%r while AI diagnostics are disabled", context)
    return CellStateSummary(
        state="Cell diagnostics disabled",
        active_objects=[],
        anomalies=[],
        safety_status="Warning",
        confidence=0.0,
    )
