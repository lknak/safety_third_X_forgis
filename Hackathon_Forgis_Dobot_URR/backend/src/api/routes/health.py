from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional
from health_service import get_health_service

router = APIRouter(prefix="/api/health", tags=["health"])

class DeviceStatus(BaseModel):
    status: str
    error: Optional[str] = None
    suggestion: Optional[str] = None

class OverallHealthResponse(BaseModel):
    overall_status: str
    devices: Dict[str, DeviceStatus]

class RetryResponse(BaseModel):
    success: bool
    message: str

@router.get("", response_model=OverallHealthResponse)
async def get_health():
    """Get the health status of all hardware devices."""
    service = get_health_service()
    return await service.get_overall_health()

@router.post("/retry", response_model=RetryResponse)
async def retry_health(device_name: Optional[str] = None):
    """Retry initialization for a specific device or all devices."""
    service = get_health_service()
    success = await service.retry_initialization(device_name)
    
    if device_name:
        message = f"Initialization retried for {device_name}. Status: {'Ready' if success else 'Failed'}"
    else:
        message = f"Initialization retried for all devices. Overall: {'Ready' if success else 'Degraded'}"
        
    return RetryResponse(success=success, message=message)
