@echo off
cd /d "%~dp0"
call .venv_calib\Scripts\activate.bat
if "%~1" == "" (
    echo Usage: run_calibration.bat [intrinsic|extrinsic] [camera_id]
    python scripts\unified_calibrate.py --mode extrinsic --camera 0
) else (
    python scripts\unified_calibrate.py --mode %1 --camera %2
)
pause
