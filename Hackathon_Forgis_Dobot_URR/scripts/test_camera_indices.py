"""Test each camera index to find which one gives proper frames."""
import cv2
import numpy as np
import time

print("Testing each camera index...")
for idx in range(5):
    for backend_id, bname in [(cv2.CAP_DSHOW, "DSHOW"), (cv2.CAP_ANY, "ANY")]:
        cap = cv2.VideoCapture(idx, backend_id)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        # Warm up
        for _ in range(15):
            cap.read()
            time.sleep(0.03)
        ret, frame = cap.read()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            m = float(np.mean(frame))
            nz = float(np.count_nonzero(frame) / frame.size * 100)
            label = "GOOD" if m > 10 else "BLACK"
            print(f"  idx={idx} ({bname}): {w}x{h} mean={m:.1f} nonzero={nz:.1f}% [{label}]")
        else:
            print(f"  idx={idx} ({bname}): no frame")
        cap.release()
        time.sleep(0.5)
print("Done")
