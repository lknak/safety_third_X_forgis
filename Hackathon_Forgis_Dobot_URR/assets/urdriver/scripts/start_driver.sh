#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash

ROBOT_IP="${ROBOT_IP:?Set ROBOT_IP in .env}"

# --- Stop any running program on the robot to release RTDE resources ---
# The UR Dashboard Server listens on port 29999.
# Sending "stop" releases RTDE variables held by running programs,
# which prevents the "speed_slider_mask controlled by another client" crash.
echo "Clearing robot state via Dashboard Server at ${ROBOT_IP}..."
python3 -c "
import socket, time
try:
    s = socket.create_connection(('${ROBOT_IP}', 29999), timeout=5)
    s.recv(1024)  # read welcome banner
    s.sendall(b'stop\n')
    time.sleep(1)
    print(s.recv(1024).decode().strip())
    s.close()
    print('Dashboard: stop sent successfully')
except Exception as e:
    print(f'Dashboard connection failed (robot may be off): {e}')
" || true
sleep 2

ros2 launch ur_robot_driver ur_control.launch.py \
  ur_type:="${UR_TYPE:-ur5e}" \
  robot_ip:="${ROBOT_IP}" \
  reverse_ip:="${REVERSE_IP:-0.0.0.0}" \
  launch_rviz:=false \
  headless_mode:=true
