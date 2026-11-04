@echo off
cd /d "%~dp0"
title Lago de Ajuchitlan - servidor
color 0E
echo =====================================================
echo   LAGO DE AJUCHITLAN - VENTANA DEL SERVIDOR
echo =====================================================
echo Carpeta: %CD%
echo.
if not exist ".env" (
  echo No se encontro .env. Ejecuta primero INICIAR_WINDOWS.bat para crear la configuracion segura.
  pause
  exit /b 1
)
echo Deja esta ventana abierta mientras usas el sitio.
echo Direccion: http://127.0.0.1:5000/
echo.
py app.py
echo.
echo El servidor se detuvo o se produjo un error al iniciarlo.
echo Toma una captura del mensaje anterior y compartela en el chat.
pause
