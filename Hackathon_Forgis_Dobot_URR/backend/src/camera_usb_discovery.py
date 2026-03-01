"""USB camera discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    return value or None


def _find_usb_ancestor(device_path: Path) -> Optional[Path]:
    for candidate in [device_path, *device_path.parents]:
        if (candidate / "idVendor").exists() and (candidate / "idProduct").exists():
            return candidate
    return None


def _find_stable_video_path(video_device: str) -> Optional[str]:
    by_id_dir = Path("/dev/v4l/by-id")
    if not by_id_dir.exists():
        return None

    for link in sorted(by_id_dir.glob("*")):
        try:
            if os.path.realpath(str(link)) == video_device:
                return str(link)
        except OSError:
            continue
    return None


def _sanitize_identifier(value: str) -> str:
    cleaned = [
        ch.lower() if ch.isalnum() else "_"
        for ch in value
    ]
    return "".join(cleaned).strip("_")


def scan_usb_cameras() -> list[dict]:
    """
    Scan Linux V4L devices and return USB camera metadata.

    Returns:
        List of camera metadata dictionaries.
    """
    if os.name != "posix":
        return []

    video_class_dir = Path("/sys/class/video4linux")
    if not video_class_dir.exists():
        return []

    discovered: list[dict] = []

    for video_dir in sorted(video_class_dir.glob("video*"), key=lambda p: p.name):
        video_device = f"/dev/{video_dir.name}"

        device_link = video_dir / "device"
        try:
            resolved_device = device_link.resolve(strict=True)
        except OSError:
            continue

        usb_ancestor = _find_usb_ancestor(resolved_device)
        if usb_ancestor is None and "usb" not in str(resolved_device).lower():
            continue

        camera_name = _read_text(video_dir / "name") or video_dir.name
        vendor_id = _read_text(usb_ancestor / "idVendor") if usb_ancestor else None
        product_id = _read_text(usb_ancestor / "idProduct") if usb_ancestor else None
        manufacturer = _read_text(usb_ancestor / "manufacturer") if usb_ancestor else None
        product = _read_text(usb_ancestor / "product") if usb_ancestor else None
        serial = _read_text(usb_ancestor / "serial") if usb_ancestor else None

        stable_path = _find_stable_video_path(video_device)
        vendor_label = manufacturer or "USB"
        product_label = product or camera_name
        label = f"{vendor_label} {product_label}".strip()

        raw_id = stable_path or video_device
        camera_id = _sanitize_identifier(raw_id) or _sanitize_identifier(video_dir.name)

        discovered.append(
            {
                "id": camera_id,
                "video_device": video_dir.name,
                "endpoint": video_device,
                "stable_path": stable_path,
                "name": camera_name,
                "label": label,
                "vendor": manufacturer or "USB Camera",
                "product": product or camera_name,
                "serial": serial,
                "vendor_id": vendor_id,
                "product_id": product_id,
                "usb_path": str(usb_ancestor) if usb_ancestor else str(resolved_device),
            }
        )

    return discovered
