@echo off
chcp 65001 >nul
setlocal
title GUIOS EVAL - Instalacion
cd /d "%~dp0"
echo ============================================================
echo   GUIOS EVAL - Instalacion
echo   1. Librerias  2. Inteligencia artificial  3. IA local  4. Verificacion
echo   No reinstala ni sobrescribe nada que ya exista.
echo ============================================================

rem ---------- 1. Python y librerias ----------
where python >nul 2>nul
if errorlevel 1 goto sin_python
echo.
echo [1/4] Librerias de Python (Flask, openpyxl, fpdf2, pytest)...
python -m pip install -r requirements.txt pytest --quiet --disable-pip-version-check
if errorlevel 1 echo       Aviso: pip no pudo instalar alguna libreria. Revisa la conexion a internet.
if not errorlevel 1 echo       Librerias listas.

rem ---------- 2. Claves de IA (Groq / Gemini) ----------
echo.
echo [2/4] Inteligencia artificial
python -m guios.configurar_ia
if errorlevel 10 goto ia_local
echo.
echo [3/4] IA local: omitida por tu eleccion.
goto verificar

rem ---------- 3. IA local: Ollama + modelo ----------
:ia_local
echo.
echo [3/4] IA local sin internet (Ollama + modelo qwen2.5:3b)...
set "OLLAMA_EXE="
for /f "delims=" %%i in ('where ollama 2^>nul') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%i"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
if defined OLLAMA_EXE goto ollama_ok
echo       Ollama no esta instalado. Instalando con winget...
winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if defined OLLAMA_EXE goto servicio
echo       No se pudo instalar Ollama. El sistema funciona igual con Groq, Gemini
echo       o sin IA. Para instalarlo a mano: https://ollama.com/download/windows
goto verificar

:ollama_ok
echo       Ollama YA esta instalado.

:servicio
"%OLLAMA_EXE%" list >nul 2>nul
if not errorlevel 1 goto modelo
echo       Iniciando el servicio de Ollama...
start "" /min "%OLLAMA_EXE%" serve
timeout /t 6 >nul

:modelo
"%OLLAMA_EXE%" list | findstr /i /c:"qwen2.5:3b" >nul
if not errorlevel 1 goto modelo_ok
echo       Descargando el modelo qwen2.5:3b, unos 2 GB, solo la primera vez...
"%OLLAMA_EXE%" pull qwen2.5:3b
goto verificar

:modelo_ok
echo       El modelo qwen2.5:3b YA esta descargado.

rem ---------- 4. Verificacion ----------
:verificar
echo.
echo [4/4] Verificando que todo funcione...
python pruebas\verificar.py
echo.
echo Para usar el sistema: doble clic en iniciar.bat
pause
exit /b

:sin_python
echo No se encontro Python. Instalalo desde https://www.python.org/downloads/
echo marcando la opcion "Add Python to PATH" y vuelve a ejecutar este archivo.
start "" https://www.python.org/downloads/
pause
