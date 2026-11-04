@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Lago de Ajuchitlan - Iniciador
color 0B
echo =====================================================
echo   LAGO DE AJUCHITLAN - INICIAR SITIO
echo =====================================================
echo.
echo Carpeta del proyecto:
echo %CD%
echo.
py --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Windows no encuentra Python. Instala Python y vuelve a intentar.
  pause
  exit /b 1
)
if not exist ".env" (
  for /f "delims=" %%K in ('py -c "import secrets; print(secrets.token_urlsafe(40))"') do set "LAGO_KEY=%%K"
  >".env" echo LAGO_SECRET_KEY=!LAGO_KEY!
  >>".env" echo LAGO_ADMIN_USER=admin
  >>".env" echo LAGO_ADMIN_PASSWORD=admin
  echo Se creo .env para esta computadora.
  echo Usuario administrador: admin
  echo Contrasena inicial de prueba: admin
  echo IMPORTANTE: cambia esta contrasena antes de publicar el sitio en internet.
  echo No compartas ni subas el archivo .env a internet o a GitHub.
  echo.
  pause
)
echo La configuracion privada se conserva en .env.
echo El archivo .env no debe subirse a GitHub ni compartirse.
echo Las contrasenas de usuarios se almacenan como hashes.
echo.
echo Comprobando si hay un servidor anterior usando el puerto 5000...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c -and $c.OwningProcess -ne $PID){ $proc=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$c.OwningProcess); if($proc -and ($proc.Name -match 'python|py.exe')) { Write-Host ('Cerrando servidor Python anterior (PID '+$c.OwningProcess+').'); Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } else { Write-Host 'El puerto 5000 esta ocupado por otro programa. Cierra ese programa y vuelve a ejecutar este archivo.'; exit 2 } }"
if errorlevel 1 (
  echo ERROR: el puerto 5000 esta ocupado por otro programa. Cierra el servidor anterior y vuelve a ejecutar.
  pause
  exit /b 1
)

echo Comprobando e instalando dependencias...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: No se pudieron instalar los requisitos. Envia una captura de esta ventana.
  pause
  exit /b 1
)
echo.
echo Iniciando el servidor para acceso local y, si la red lo permite, desde otro equipo. No cierres la ventana del servidor.
start "Lago de Ajuchitlan - servidor" /D "%~dp0" cmd.exe /k "py app.py"
echo Esperando a que el servidor responda...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:5000/'; $ok=$false; for($i=0;$i -lt 30;$i++){ try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {} ; Start-Sleep -Seconds 1 }; if($ok){ Start-Process $url; Write-Host 'Correcto: se abrio el sitio.' } else { Write-Host ''; Write-Host 'ERROR: el servidor no respondio.'; Write-Host 'Revisa la ventana negra Lago de Ajuchitlan - servidor.'; Read-Host 'Presiona Enter para cerrar' }"
endlocal
