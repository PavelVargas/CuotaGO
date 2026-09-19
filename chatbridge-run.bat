@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo =============================================
echo          CuotaGo - ChatBridge Run
echo =============================================
echo.

if exist "INICIAR_WINDOWS.bat" (
  call "INICIAR_WINDOWS.bat"
  exit /b %errorlevel%
)

echo ERROR: No se encontro INICIAR_WINDOWS.bat en la raiz del proyecto.
echo El proyecto Flask necesita ese lanzador o una configuracion equivalente.
echo.
pause
exit /b 1
