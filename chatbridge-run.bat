@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ===============================================
echo   CuotaGO - REVISION LOCAL / PREPRODUCCION
echo ===============================================
echo Este lanzador NO usa la base operativa de .env.
echo.
if exist ".venv\Scripts\python.exe" goto deps
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3 -m venv .venv
if errorlevel 1 goto failed
goto deps
:pythonfallback
where python >nul 2>nul
if errorlevel 1 goto nopython
python -m venv .venv
if errorlevel 1 goto failed
:deps
".venv\Scripts\python.exe" -c "import flask, flask_sqlalchemy, flask_login, flask_wtf, flask_compress, psycopg, dotenv, cryptography, reportlab, pywebpush, apscheduler, pytest, fitz" >nul 2>nul
if not errorlevel 1 goto start
echo Preparando dependencias dentro de .venv, sin permisos de administrador...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-test.txt
if errorlevel 1 goto failed
:start
".venv\Scripts\python.exe" tools\preproduction.py %*
if errorlevel 1 goto failed
exit /b 0
:nopython
echo ERROR: Python no esta disponible. Usa una instalacion por usuario autorizada.
goto failed
:failed
echo.
echo El arranque o la verificacion fallo. Revisa el mensaje anterior.
echo No se modifico la configuracion operativa ni se desplego a produccion.
pause
exit /b 1
