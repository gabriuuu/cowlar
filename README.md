# 🐮 Cowlar — Sistema de Monitoreo Ganadero Inteligente con LoRaWAN

> **Proyecto de Grado de Bachillerato Técnico — República del Ecuador (2026 - 2027)**  
> **Tema:** Monitoreo y Geolocalización de Ganado Vacuno mediante Tecnología LoRaWAN en Zonas Rurales Aisladas sin Cobertura de Internet.

---

## 📖 1. ¿Qué es Cowlar?

**Cowlar** es una plataforma web integral diseñada para la ingesta, visualización y análisis del comportamiento de ganado bovino en tiempo real. 

El sistema resuelve el problema de las haciendas aisladas en el campo:
1. El **Collar (Heltec ESP32-S3 + GPS NEO-6M + Acelerómetro MPU-6050)** colocado en la vaca recopila su ubicación satelital, nivel de batería e inclinación del cuello.
2. Transmite los datos a varios kilómetros mediante radiofrecuencia **LoRa (915 MHz)** sin necesidad de cobertura celular ni internet en el potrero.
3. El **Gateway Dragino LPS8N**, ubicado en la casa de hacienda y conectado por cable de red (Ethernet), recibe los paquetes y los sube a la nube de **The Things Network (TTN)**.
4. **Cowlar** recibe los datos desde TTN vía Webhook, los almacena en su base de datos local SQLite y los presenta en un panel visual interactivo.

---

## 🚀 2. ¿Cómo Iniciar la Aplicación?

Solo necesitas hacer **doble clic** sobre el archivo:
📁 `iniciar_cowlar.bat`

Esto abrirá automáticamente la consola del servidor y tu navegador web en:
👉 **[http://localhost:8000](http://localhost:8000)**

*(No requiere instalar paquetes externos de Python ni Node.js. Funciona al 100% con las librerías estándar del sistema).*

---

## 🌟 3. Características Principales de la Aplicación

### 🗺️ A. Mapa Interactivo y Cerco Virtual (Geofence)
* **Visualización Satelital / Callejera:** Alterna entre OpenStreetMap y fotografía satelital de alta resolución (ESRI).
* **Perímetro de Seguridad (100 x 100 m):** Dibuja el potrero seguro. Si el animal sale de esta zona, el sistema activa una **alarma visual parpadeante y sonora**.
* **Rastro de Movimiento (Breadcrumbs):** Muestra la trayectoria que ha recorrido la vaca durante el día.

### 🐮 B. Monitor de Postura y Pastoreo (MPU-6050)
* **Horizonte Artificial y Ángulo de Cuello (Pitch & Roll):**
  * `Pitch < -22°`: **Pastando** (cabeza agachada comiendo forraje).
  * `Pitch entre -18° y 15° con movimiento oscilatorio suave`: **Rumia** (masticación rítmica en reposo).
  * `Sin movimiento`: **Reposo**.
  * `Aceleración > 0.7g`: **Caminando** o **Agitado** (posible estrés o depredador).

### 🔋 C. Estado de Energía y Radio LoRa
* **Batería 1S 3.7V (Li-Ion / 18650):** Indicador visual de porcentaje y voltaje con advertencia automática si la batería baja de 3.3V.
* **Calidad de Señal:** Monitoreo de RSSI (dBm) y SNR (dB) reportados por el Gateway Dragino.

### 📋 D. Registro Histórico y Exportación Excel
* Tabla en tiempo real con todas las tramas recibidas.
* Botón **"Exportar CSV"** para descargar la información directamente y tabularla en Microsoft Excel o Google Sheets para el informe de grado.

### 🧪 E. Modo Simulación para la Defensa de Grado
Durante la sustentación o revisiones con el tutor de tesis, pueden activar el **Modo Demostración en Vivo**:
* Hace que la vaca se mueva de forma natural por el potrero cada 4 segundos.
* Botones para probar escenarios al instante:
  * *Simular Vaca Escapando del Potrero* (dispara la alerta roja y el sonido de advertencia).
  * *Simular Batería Baja*.
  * *Simular Agitación o Golpe Brusco*.

---

## 🛰️ 4. Configuración con The Things Network (TTN)

Para conectar el Gateway Dragino a Cowlar:
1. En la consola de TTN, ingresa a tu aplicación y ve a **Integrations &gt; Webhooks**.
2. Crea un **Custom Webhook** con:
   * **Webhook ID:** `cowlar-webhook`
   * **Base URL:** `http://TU_IP:8000/api/ttn/webhook` *(o tu URL pública de ngrok si pruebas en remoto)*.
3. En **Payload formatters &gt; Uplink**, copia y pega el código decodificador disponible en la pestaña *"🛰️ Enlace TTN & Gateway"* de Cowlar.

---

## 💻 5. Código para el ESP32 Heltec V3

El código fuente en C++ para cargar en la placa del collar se encuentra en la carpeta:
📁 `arduino/Cowlar_Node.ino`

Incluye:
* Inicialización de I2C en `GPIO 41` y `GPIO 42` para el MPU-6050.
* Puerto UART2 en `GPIO 19` (RX) y `GPIO 20` (TX) para el GPS NEO-6M.
* Lectura del divisor resistivo de batería en el pin `1`.
* Empaquetado binario de 14 bytes para mínima transmisión de radio.
* Modo **Deep Sleep** para maximizar la duración de la batería 18650 hasta 2 meses.

---

## 👥 6. Créditos del Proyecto
* **Proyecto:** Collar Inteligente LoRaWAN "Cowlar".
* **Institución:** República del Ecuador.
* **Nivel:** 3ro de Bachillerato Técnico.
* **Año Lectivo:** 2026 - 2027.
