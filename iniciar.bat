@echo off
chcp 65001 >nul
title GUIOS EVAL
cd /d "%~dp0"
echo ============================================
echo   GUIOS EVAL - Iniciando el sistema...
echo   No cierres esta ventana mientras lo usas.
echo ============================================
where python >nul 2>nul
if errorlevel 1 goto sin_python
python -c "import flask, openpyxl, fpdf, segno" >nul 2>nul
if errorlevel 1 goto faltan
start "" http://127.0.0.1:5000
python -m guios
pause
exit /b

:faltan
echo Faltan librerias de la nueva version. Instalando...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto fallo_pip
start "" http://127.0.0.1:5000
python -m guios
pause
exit /b

:sin_python
echo No se encontro Python. Ejecuta instalar.bat o instala Python desde
echo https://www.python.org/downloads/ marcando "Add Python to PATH".
pause
exit /b

:fallo_pip
echo No se pudieron instalar las librerias. Ejecuta instalar.bat
pause
