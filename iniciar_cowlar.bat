@echo off
title Cowlar - Sistema de Monitoreo Ganadero LoRaWAN
color 0A
cd /d "%~dp0"

echo =====================================================================
echo                 COWLAR - SISTEMA GANADERO LORAWAN
echo       Monitoreo de Pastoreo, Geolocalizacion y Bienestar Bovino
echo            Proyecto de Grado - 3ro de Bachillerato Ecuador
echo =====================================================================
echo.
echo [1/2] Verificando entorno de ejecucion...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no se encuentra instalado o no esta en el PATH.
    echo Por favor asegurese de tener Python 3 instalado.
    pause
    exit /b
)

echo [2/2] Abriendo Dashboard de Cowlar en el navegador...
timeout /t 2 /nobreak >nul
start http://localhost:8000

echo.
echo Servidor Cowlar activo y escuchando en:
echo - Dashboard Web:        http://localhost:8000
echo - Enlace MQTT TTN:      nam1.cloud.thethings.network:8883 (Activo y directo)
echo - Webhook para TTN:     http://localhost:8000/api/ttn/webhook
echo.
echo Presione Ctrl + C para detener el servidor cuando termine.
echo.

python server.py
pause
