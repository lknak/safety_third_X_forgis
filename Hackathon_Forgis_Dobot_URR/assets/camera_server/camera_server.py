"""
USB Camera WebSocket Server.

Supports:
1) Intel RealSense (if pyrealsense2 + camera available)
2) Generic UVC webcams (OpenCV VideoCapture, auto index scan)

Usage:
    python camera_server.py --port 8765 --fps 30 --width 640 --height 480 --mode auto
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from typing import Optional

import cv2
import numpy as np
import websockets

try:
    import pyrealsense2 as rs
except ImportError:
    rs = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RealSenseCapture:
    """Captures BGR frames from an Intel RealSense camera."""

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.pipeline: Optional["rs.pipeline"] = None
        self.config: Optional["rs.config"] = None

    def start(self) -> bool:
        """Initialize and start the RealSense pipeline."""
        if rs is None:
            logger.warning("pyrealsense2 not installed; skipping RealSense backend")
            return False

        try:
            self.pipeline = rs.pipeline()
            self.config = rs.config()
            self.config.enable_stream(
                rs.stream.color, self.width, self.height, rs.format.rgb8, self.fps
            )
            self.pipeline.start(self.config)
            logger.info(
                "RealSense started: %dx%d @ %d FPS",
                self.width,
                self.height,
                self.fps,
            )
            return True
        except Exception as e:
            logger.error("Failed to start RealSense: %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        """Stop the RealSense pipeline."""
        if self.pipeline:
            try:
                self.pipeline.stop()
            except Exception:
                pass
        self.pipeline = None
        self.config = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame as BGR ndarray."""
        if not self.pipeline:
            return None

        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=1000)
            color_frame = frames.get_color_frame()
            if not color_frame:
                return None
            frame_rgb = np.asanyarray(color_frame.get_data())
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            return frame_bgr
        except Exception as e:
            logger.error("RealSense frame error: %s", e)
            return None


class UvcCapture:
    """Captures BGR frames from a generic USB webcam using OpenCV."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        device_index: Optional[int] = None,
        scan_max_index: int = 10,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.device_index = device_index
        self.scan_max_index = scan_max_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.active_index: Optional[int] = None

    def _candidate_indices(self) -> list[int]:
        if self.device_index is not None:
            return [self.device_index]
        # On Windows, DirectShow backend (cv2.CAP_DSHOW) is more reliable.
        # Indices 0-4 typically cover all connected cameras.
        return list(range(0, self.scan_max_index + 1))

    def _open_index(self, index: int) -> Optional[cv2.VideoCapture]:
        # On Windows, try DirectShow first (more reliable for USB cameras),
        # then fall back to default backend.
        backends = [cv2.CAP_DSHOW, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]

        for backend in backends:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
            cap.set(cv2.CAP_PROP_FPS, float(self.fps))

            ok = False
            for _ in range(5):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    ok = True
                    break
                time.sleep(0.05)

            if ok:
                backend_name = "DirectShow" if backend == cv2.CAP_DSHOW else "default"
                logger.info("Opened camera index %d with %s backend", index, backend_name)
                return cap

            cap.release()

        return None

    def start(self) -> bool:
        """Try to connect to a webcam by index."""
        for index in self._candidate_indices():
            cap = self._open_index(index)
            if cap is None:
                continue

            self.cap = cap
            self.active_index = index
            logger.info(
                "UVC camera started on index %d: %dx%d @ %d FPS",
                index,
                self.width,
                self.height,
                self.fps,
            )
            return True

        logger.error("Failed to open any UVC camera index")
        return False

    def stop(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self.active_index = None

    def get_frame(self) -> Optional[np.ndarray]:
        if self.cap is None:
            return None

        ret, frame = self.cap.read()
        if not ret or frame is None or frame.size == 0:
            return None
        return frame


class CameraServer:
    """WebSocket server that streams camera frames to connected clients."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        fps: int = 30,
        width: int = 640,
        height: int = 480,
        jpeg_quality: int = 80,
        mode: str = "auto",
        device_index: Optional[int] = None,
        scan_max_index: int = 10,
    ):
        self.host = host
        self.port = port
        self.fps = fps
        self.jpeg_quality = jpeg_quality
        self.mode = (mode or "auto").strip().lower()
        self.device_index = device_index
        self.scan_max_index = scan_max_index

        self.width = width
        self.height = height
        self.camera = None
        self.clients: set = set()
        self.running = False
        self._frame_interval = 1.0 / max(1, fps)
        self._last_camera_attempt = 0.0

    def _build_capture(self):
        if self.mode == "realsense":
            rs_cap = RealSenseCapture(self.width, self.height, self.fps)
            if rs_cap.start():
                logger.info("Camera backend selected: realsense")
                return rs_cap
            rs_cap.stop()
            return None
        if self.mode == "uvc":
            uvc_cap = UvcCapture(
                self.width,
                self.height,
                self.fps,
                device_index=self.device_index,
                scan_max_index=self.scan_max_index,
            )
            if uvc_cap.start():
                logger.info("Camera backend selected: uvc")
                return uvc_cap
            uvc_cap.stop()
            return None

        # auto mode: try RealSense first, then UVC.
        if rs is not None:
            rs_cap = RealSenseCapture(self.width, self.height, self.fps)
            if rs_cap.start():
                logger.info("Camera backend selected: realsense")
                return rs_cap
            rs_cap.stop()

        uvc_cap = UvcCapture(
            self.width,
            self.height,
            self.fps,
            device_index=self.device_index,
            scan_max_index=self.scan_max_index,
        )
        if uvc_cap.start():
            logger.info("Camera backend selected: uvc")
            return uvc_cap
        uvc_cap.stop()
        return None

    def _ensure_camera(self) -> bool:
        if self.camera is not None:
            return True

        now = time.time()
        if now - self._last_camera_attempt < 2.0:
            return False

        self._last_camera_attempt = now
        camera = self._build_capture()
        if camera is None:
            logger.warning("No camera backend available (mode=%s). Retrying...", self.mode)
            return False

        self.camera = camera
        return True

    def _drop_camera(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception:
                pass
        self.camera = None

    async def register_client(self, websocket) -> None:
        """Register a new client and keep connection alive."""
        client_addr = websocket.remote_address
        logger.info("Client connected: %s", client_addr)
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)
            logger.info("Client disconnected: %s", client_addr)

    async def broadcast_frames(self) -> None:
        """Capture and broadcast frames to all connected clients."""
        consecutive_failures = 0

        while self.running:
            if not self.clients:
                await asyncio.sleep(0.1)
                continue

            if not self._ensure_camera():
                await asyncio.sleep(0.25)
                continue

            frame = self.camera.get_frame() if self.camera is not None else None
            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    logger.warning("Camera read failed repeatedly; reinitializing backend")
                    self._drop_camera()
                    consecutive_failures = 0
                await asyncio.sleep(0.03)
                continue

            consecutive_failures = 0

            encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            success, jpeg_data = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                await asyncio.sleep(0.01)
                continue

            jpeg_bytes = jpeg_data.tobytes()
            websockets.broadcast(self.clients, jpeg_bytes)
            await asyncio.sleep(self._frame_interval)

    async def start(self) -> None:
        """Start the WebSocket server and camera loop."""
        self.running = True
        broadcast_task = asyncio.create_task(self.broadcast_frames())

        logger.info("WebSocket server starting on ws://%s:%d", self.host, self.port)
        try:
            async with websockets.serve(
                self.register_client,
                self.host,
                self.port,
                ping_interval=None,
            ):
                await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
            self._drop_camera()

    def stop(self) -> None:
        """Signal the server to stop."""
        self.running = False


def main():
    parser = argparse.ArgumentParser(
        description="USB Camera WebSocket Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0", help="Server bind address")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument("--fps", type=int, default=30, help="Camera FPS")
    parser.add_argument("--width", type=int, default=640, help="Frame width")
    parser.add_argument("--height", type=int, default=480, help="Frame height")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality (0-100)")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "realsense", "uvc"],
        help="Camera backend mode",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="Preferred UVC device index (only for --mode uvc/auto)",
    )
    parser.add_argument(
        "--scan-max-index",
        type=int,
        default=10,
        help="Maximum UVC index to scan in auto mode",
    )
    args = parser.parse_args()

    server = CameraServer(
        host=args.host,
        port=args.port,
        fps=args.fps,
        width=args.width,
        height=args.height,
        jpeg_quality=args.quality,
        mode=args.mode,
        device_index=args.device_index,
        scan_max_index=args.scan_max_index,
    )

    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
