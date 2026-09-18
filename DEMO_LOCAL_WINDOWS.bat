@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo =============================================
echo        CuotaGo - DEMO LOCAL EN EL LOCAL
echo =============================================
echo.

if not exist ".env" (
  echo ERROR: Falta el archivo .env incluido con el proyecto.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python no esta instalado o no esta en PATH.
  echo Instala Python 3.11 o superior y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo [1/4] Creando entorno virtual...
  python -m venv venv
  if errorlevel 1 goto :error
) else (
  echo [1/4] Entorno virtual encontrado.
)

call "venv\Scripts\activate.bat"

echo [2/4] Instalando/verificando dependencias...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

echo [3/4] Verificando CuotaGo y PostgreSQL...
python scripts\doctor.py
if errorlevel 1 goto :error

set "LAN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue ^| Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254*' }; $ip = $ips ^| Sort-Object InterfaceMetric ^| Select-Object -First 1 -ExpandProperty IPAddress; if ($ip) { $ip }"`) do set "LAN_IP=%%I"

echo.
echo =============================================
echo DEMOSTRACION LISTA
if defined LAN_IP (
  echo En esta PC:      http://127.0.0.1:5000
  echo En el telefono:  http://%LAN_IP%:5000
) else (
  echo En esta PC:      http://127.0.0.1:5000
  echo No pude detectar la IP Wi-Fi automaticamente.
  echo Ejecuta ipconfig y usa la IPv4 de esta PC con :5000
)
echo.
echo IMPORTANTE:
echo - PC y telefono deben estar en la misma red Wi-Fi.
echo - Si Windows pregunta por Firewall, permite Redes privadas.
echo - Para la demo local NO necesitas dominio ni HTTPS.
echo - Las notificaciones Push con la app cerrada se activaran mas adelante con HTTPS.
echo - No aparece ningun aviso de notificaciones en Inicio; eso esta solo en Ajustes.
echo =============================================
echo.

echo [4/4] Iniciando CuotaGo...
python app.py
if errorlevel 1 goto :error
goto :end

:error
echo.
echo Ocurrio un error. Revisa el mensaje anterior.
pause
exit /b 1

:end
pause
