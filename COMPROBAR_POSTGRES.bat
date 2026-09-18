@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo        CuotaGo - comprobar PostgreSQL
echo =============================================

if not exist "venv\Scripts\python.exe" (
  python -m venv venv
  if errorlevel 1 goto :error
)
call "venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error
python scripts\doctor.py
if errorlevel 1 goto :error

echo.
echo PostgreSQL OK. Puedes iniciar CuotaGo con INICIAR_WINDOWS.bat
pause
exit /b 0

:error
echo.
echo ERROR: No se pudo conectar a PostgreSQL.
echo Verifica que PostgreSQL este iniciado y que exista la base cuotago.
echo PostgreSQL se comprobara usando DATABASE_URL de tu .env
pause
exit /b 1
