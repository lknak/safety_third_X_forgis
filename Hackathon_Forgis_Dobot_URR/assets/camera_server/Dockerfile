FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    opencv-python-headless \
    pyrealsense2 \
    websockets \
    numpy

COPY assets/camera_server/camera_server.py .

EXPOSE 8765

# Unbuffered python output
CMD ["python", "-u", "camera_server.py", "--host", "0.0.0.0", "--port", "8765"]
