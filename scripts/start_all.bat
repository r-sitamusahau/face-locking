@echo off
setlocal
cd /d "%~dp0.."

echo === FaceLocking startup ===

where python >nul 2>&1 || (echo Python not found & exit /b 1)
where node >nul 2>&1 || (echo Node.js not found & exit /b 1)

if not exist "models\embedder_arcface.onnx" (
  echo Missing models\embedder_arcface.onnx
  echo Run: python scripts\download_model.py
  exit /b 1
)

if not exist "data\db\face_db.npz" (
  echo No face database found. Enrolling default user "ruth"...
  python -m src.enroll --name ruth --auto --camera 1
  if errorlevel 1 exit /b 1
)

echo Starting MQTT broker...
start "MQTT Broker" cmd /k "cd backend && npm run broker"

timeout /t 2 /nobreak >nul

echo Starting backend + dashboard...
start "Backend" cmd /k "cd backend && npm start"

timeout /t 2 /nobreak >nul

echo Starting vision node — pick speaker when prompted...
start "Vision Node" cmd /k "python src\vision_node.py --broker 127.0.0.1 --pick --camera 1"

timeout /t 3 /nobreak >nul
start "" "http://localhost:8080"

echo.
echo All services started.
echo Dashboard: http://localhost:8080
echo Press Q in the Vision Node window to quit tracking.
