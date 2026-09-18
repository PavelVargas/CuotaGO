@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo          CuotaGo - inicio local real
echo =============================================

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

echo [3/4] Verificando PostgreSQL...
python scripts\doctor.py
if errorlevel 1 goto :error

echo [4/4] Iniciando CuotaGo en http://127.0.0.1:5000
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
