@echo off
setlocal
cd /d "%~dp0"

docker version >nul 2>nul
if errorlevel 1 (
  echo ERROR: Docker Desktop no esta instalado o no esta iniciado.
  pause
  exit /b 1
)

echo Construyendo e iniciando CuotaGo + PostgreSQL...
docker compose up -d --build
if errorlevel 1 (
  echo ERROR: No se pudo iniciar Docker Compose.
  pause
  exit /b 1
)

echo.
echo CuotaGo: http://127.0.0.1:8080
echo Estado:  http://127.0.0.1:8080/healthz
pause
