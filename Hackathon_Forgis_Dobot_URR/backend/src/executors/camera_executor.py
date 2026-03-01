"""Camera executor for YOLO detection, AI Vision, and frame streaming."""

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np
from ai_service import ai_service

from .base import Executor

if TYPE_CHECKING:
    from api.websocket import WebSocketManager
    from nodes.camera_node import CameraNode

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """Detected object bounding box."""

    x: float
    y: float
    width: float
    height: float
    confidence: float
    class_name: str

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "class_name": self.class_name,
        }


class CameraExecutor(Executor):
    """
    Executor for camera operations including YOLO detection and AI Vision.

    Provides streaming, object detection, and OCR capabilities.
    """

    executor_type = "camera"

    def __init__(self, camera_node: "CameraNode", ws_manager: "WebSocketManager"):
        self._camera = camera_node
        self._ws = ws_manager

        # Streaming state
        self._streaming = False
        self._stream_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._frame_queue: Optional[asyncio.Queue] = None

        # YOLO model (lazy loaded)
        self._yolo_model = None
        self._yolo_model_name = os.environ.get("YOLO_MODEL", "/app/weights/roboflow_logistics.pt")

        # AI service
        self._ai_service = ai_service

        # Last detection result for cropping
        self._last_bbox: Optional[BoundingBox] = None

    async def initialize(self) -> None:
        """Wait for camera frames to start arriving."""
        logger.info("CameraExecutor initializing...")
        timeout = 10.0
        elapsed = 0.0
        while not self._camera.has_frame() and elapsed < timeout:
            await asyncio.sleep(0.1)
            elapsed += 0.1

        if not self._camera.has_frame():
            logger.warning("Camera frame not available after timeout - camera may not be connected")
        else:
            dims = self._camera.get_frame_dimensions()
            logger.info(f"CameraExecutor ready - frame size: {dims}")

    async def shutdown(self) -> None:
        """Stop streaming and cleanup."""
        await self.stop_streaming()

    def is_ready(self) -> bool:
        """Check if camera has received frames."""
        return self._camera.has_frame()

    def _get_yolo_model(self):
        """Lazy-load YOLO model on first use."""
        if self._yolo_model is None:
            from ultralytics import YOLO

            logger.info(f"Loading YOLO model: {self._yolo_model_name}")
            self._yolo_model = YOLO(self._yolo_model_name)
            logger.info("YOLO model loaded")
        return self._yolo_model

    # --- Streaming ---

    async def start_streaming(self, fps: int = 15, max_queue: int = 1) -> bool:
        """Start streaming camera frames over WebSocket."""
        if self._streaming:
            logger.warning("Streaming already active")
            return False

        self._streaming = True
        self._frame_queue = asyncio.Queue(maxsize=max_queue)
        self._stream_task = asyncio.create_task(self._capture_loop(fps))
        self._send_task = asyncio.create_task(self._send_loop())
        logger.info(f"Camera streaming started at {fps} FPS")
        return True

    async def stop_streaming(self) -> bool:
        """Stop streaming camera frames."""
        if not self._streaming:
            return False

        self._streaming = False

        for task in [self._stream_task, self._send_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._stream_task = None
        self._send_task = None
        self._frame_queue = None

        logger.info("Camera streaming stopped")
        return True

    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        return self._streaming

    async def _capture_loop(self, fps: int) -> None:
        """Capture frames and put them in the queue, dropping old ones if full."""
        interval = 1.0 / fps

        while self._streaming:
            try:
                frame_jpeg = self._camera.get_frame_jpeg(quality=70)
                if frame_jpeg and self._frame_queue:
                    dims = self._camera.get_frame_dimensions()
                    width, height = dims if dims else (640, 480)

                    frame_data = {
                        "frame": base64.b64encode(frame_jpeg).decode(),
                        "width": width,
                        "height": height,
                    }

                    if self._frame_queue.full():
                        try:
                            self._frame_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass

                    try:
                        self._frame_queue.put_nowait(frame_data)
                    except asyncio.QueueFull:
                        pass

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Capture error: {e}")
                await asyncio.sleep(interval)

    async def _send_loop(self) -> None:
        """Send frames from the queue to WebSocket clients."""
        while self._streaming:
            try:
                if self._frame_queue:
                    frame_data = await asyncio.wait_for(
                        self._frame_queue.get(), timeout=0.033
                    )
                    await self._ws.broadcast("camera_frame", frame_data)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Send error: {e}")

    # --- Object Detection ---

    async def detect_objects(
        self,
        class_name: Optional[str] = None,
        confidence_threshold: float = 0.5,
    ) -> list[BoundingBox]:
        """Run YOLO object detection on current frame."""
        frame = self._camera.get_latest_frame()
        if frame is None:
            logger.warning("No frame available for detection")
            return []

        logger.info(f"detect_objects: frame shape={frame.shape}, class='{class_name}' conf>={confidence_threshold}")

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._get_yolo_model()(frame, verbose=False),
        )

        detections: list[BoundingBox] = []
        model = self._get_yolo_model()

        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls)
                cls_name = model.names[cls_id]
                conf = float(box.conf)
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                if conf < confidence_threshold:
                    continue
                if class_name and cls_name.lower() != class_name.lower():
                    continue

                detections.append(BoundingBox(
                    x=x1, y=y1,
                    width=x2 - x1, height=y2 - y1,
                    confidence=conf, class_name=cls_name,
                ))

        if detections:
            self._last_bbox = detections[0]
            try:
                await self._broadcast_bbox(detections[0])
            except Exception as e:
                logger.error(f"bbox broadcast failed: {e}")

        logger.info(f"detect_objects: {len(detections)} detections")
        return detections

    async def _broadcast_bbox(self, bbox: BoundingBox) -> None:
        """Broadcast bounding box to frontend for overlay display."""
        dims = self._camera.get_frame_dimensions()
        width, height = dims if dims else (640, 480)
        await self._ws.broadcast("bounding_box", {
            "bbox": bbox.to_dict(),
            "frame_width": width,
            "frame_height": height,
            "display_duration_ms": 5000,
        })

    def get_last_bbox(self) -> Optional[BoundingBox]:
        """Get the last detected bounding box."""
        return self._last_bbox

    # --- AI Vision / OCR ---

    async def read_label(
        self,
        prompt: str,
        use_bbox: bool = True,
        crop_margin: float = 0.1,
    ) -> dict:
        """Use AI Vision to read text/labels from the image."""
        await asyncio.sleep(1.5)

        frame = self._camera.get_latest_frame()
        if frame is None:
            return {"success": False, "label": "", "error": "No frame available"}

        frame, _, _ = self._crop_to_pick_zone(frame)

        success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not success:
            return {"success": False, "label": "", "error": "Failed to encode image"}

        image_bytes = encoded.tobytes()

        try:
            response_text = await self._ai_service.analyze_image(prompt, image_bytes)
            logger.info(f"Vision response: {response_text[:100]}...")
            return {"success": True, "label": response_text.strip()}
        except asyncio.TimeoutError:
            return {"success": False, "label": "", "error": "Vision timeout"}
        except Exception as e:
            logger.error(f"Vision error: {e}")
            return {"success": False, "label": "", "error": str(e)}

    async def check_quality(
        self,
        prompt: str,
        use_bbox: bool = False,
        crop_margin: float = 0.1,
    ) -> dict:
        """Use AI Vision to check if a label is readable."""
        await asyncio.sleep(1.5)

        frame = self._camera.get_latest_frame()
        if frame is None:
            return {"success": False, "readable": False, "error": "No frame available"}

        frame, _, _ = self._crop_to_pick_zone(frame)

        success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not success:
            return {"success": False, "readable": False, "error": "Failed to encode image"}

        image_bytes = encoded.tobytes()

        try:
            response_text = await self._ai_service.analyze_image(prompt, image_bytes)
            readable = "READABLE" in response_text.upper() and "NOT_READABLE" not in response_text.upper()
            return {"success": True, "readable": readable, "raw_response": response_text}
        except asyncio.TimeoutError:
            return {"success": False, "readable": False, "error": "Vision timeout"}
        except Exception as e:
            logger.error(f"check_quality error: {e}")
            return {"success": False, "readable": False, "error": str(e)}

    def _crop_to_pick_zone(self, frame: np.ndarray) -> tuple[np.ndarray, int, int]:
        """Crop frame to the fixed pick zone (300x350 at center + 70px right, + 15px down)."""
        h, w = frame.shape[:2]
        cx = w // 2 + 70
        cy = h // 2 + 15
        crop_w, crop_h = 300, 350
        x1 = max(0, cx - crop_w // 2)
        y1 = max(0, cy - crop_h // 2)
        x2 = min(w, x1 + crop_w)
        y2 = min(h, y1 + crop_h)
        return frame[y1:y2, x1:x2], x1, y1

    def _crop_to_bbox(self, frame: np.ndarray, bbox: BoundingBox, margin: float = 0.1) -> np.ndarray:
        """Crop frame to bounding box with margin."""
        h, w = frame.shape[:2]
        margin_x = bbox.width * margin
        margin_y = bbox.height * margin
        x1 = max(0, int(bbox.x - margin_x))
        y1 = max(0, int(bbox.y - margin_y))
        x2 = min(w, int(bbox.x + bbox.width + margin_x))
        y2 = min(h, int(bbox.y + bbox.height + margin_y))
        return frame[y1:y2, x1:x2]

    # --- Snapshot ---

    def get_snapshot_jpeg(self, quality: int = 90) -> Optional[bytes]:
        """Get current frame as JPEG for REST endpoint."""
        return self._camera.get_frame_jpeg(quality=quality)

    def get_state_summary(self) -> dict:
        """Get camera state summary."""
        dims = self._camera.get_frame_dimensions()
        return {
            "connected": self._camera.has_frame(),
            "streaming": self._streaming,
            "frame_size": {"width": dims[0], "height": dims[1]} if dims else None,
            "last_detection": self._last_bbox.to_dict() if self._last_bbox else None,
            "input_mode": os.environ.get("CAMERA_INPUT_MODE", "bridge").strip().lower(),
        }
