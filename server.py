import http.server
import socketserver
import urllib.parse
import json
import sqlite3
import os
import sys
import math
import random
from datetime import datetime, timezone, timedelta
from database import get_db, init_db, now_iso
from mqtt_manager import TTNMqttManager, save_config

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_static_dir():
    # 1. Buscar carpeta static estándar
    cand1 = os.path.join(BASE_DIR, "static")
    if os.path.exists(os.path.join(cand1, "index.html")):
        return cand1
    # 2. Buscar si index.html quedó suelto en la raíz del repositorio
    if os.path.exists(os.path.join(BASE_DIR, "index.html")):
        return BASE_DIR
    # 3. Buscar en el directorio de trabajo actual (CWD)
    cand3 = os.path.join(os.getcwd(), "static")
    if os.path.exists(os.path.join(cand3, "index.html")):
        return cand3
    if os.path.exists(os.path.join(os.getcwd(), "index.html")):
        return os.getcwd()
    return cand1

STATIC_DIR = get_static_dir()

# Variable global para el gestor MQTT
mqtt_mgr = None

# Haversine distance in meters
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

# Behavior Classifier based on MPU-6050 Accelerometer
def classify_activity(pitch, roll, motion):
    if motion > 1.8:
        return "Agitado"
    elif motion > 0.65:
        return "Caminando"
    elif pitch <= -22.0:
        return "Pastando"
    elif -18.0 < pitch < 15.0 and 0.08 <= motion <= 0.35:
        return "Rumia"
    else:
        return "Reposo"

def ingest_telemetry_payload(payload):
    """
    Función unificada que procesa paquetes de telemetría provenientes de:
    - Cliente MQTT en vivo (The Things Network)
    - Webhook HTTP (JSON POST)
    - Banco de pruebas / Simulador
    """
    # 1. Extraer ID del collar / vaca
    collar_id = "COW-01"
    if "end_device_ids" in payload:
        collar_id = payload["end_device_ids"].get("device_id", "COW-01").upper()
        if "01" in collar_id: collar_id = "COW-01"
        elif "02" in collar_id: collar_id = "COW-02"
        elif "03" in collar_id: collar_id = "COW-03"
    elif "collar_id" in payload:
        collar_id = str(payload["collar_id"]).upper()

    # 2. Extraer telemetría (decoded_payload o campos directos)
    data = {}
    if "uplink_message" in payload and "decoded_payload" in payload["uplink_message"]:
        data = payload["uplink_message"]["decoded_payload"]
    elif "decoded_payload" in payload:
        data = payload["decoded_payload"]
    else:
        data = payload

    # 3. Metadatos de Radio LoRaWAN y Gateway
    rssi = -80
    snr = 9.0
    gateway_id = "heltec-htm7603-hacienda"
    if "uplink_message" in payload and "rx_metadata" in payload["uplink_message"]:
        rx_list = payload["uplink_message"]["rx_metadata"]
        if rx_list and len(rx_list) > 0:
            first_rx = rx_list[0]
            rssi = first_rx.get("rssi", -80)
            snr = first_rx.get("snr", 9.0)
            if "gateway_ids" in first_rx:
                gateway_id = first_rx["gateway_ids"].get("gateway_id", gateway_id)
    elif "rssi" in data:
        rssi = int(data.get("rssi", -80))
        snr = float(data.get("snr", 9.0))
        gateway_id = data.get("gateway_id", gateway_id)

    # 4. Valores GPS
    lat = float(data.get("lat") or data.get("latitude") or -0.3245)
    lng = float(data.get("lng") or data.get("lon") or data.get("longitude") or -78.4520)
    alt = float(data.get("alt") or data.get("altitude") or 2650.0)
    speed = float(data.get("speed") or data.get("speed_kmh") or 0.0)
    sats = int(data.get("sats") or data.get("satellites") or 8)
    hdop = float(data.get("hdop") or 1.2)

    # 5. Acelerómetro MPU-6050 y Comportamiento
    pitch = float(data.get("pitch") or -30.0)
    roll = float(data.get("roll") or 2.0)
    motion = float(data.get("motion") or data.get("motion_index") or 0.3)
    activity = data.get("activity") or classify_activity(pitch, roll, motion)

    # 6. Batería Li-Ion
    batt_v = float(data.get("batt_v") or data.get("battery_v") or 3.95)
    batt_pct = int(data.get("batt_pct") or data.get("battery_pct") or int(max(0, min(100, (batt_v - 3.2) / (4.15 - 3.2) * 100))))

    timestamp = now_iso()

    # 7. Verificación de Geocerca (100x100m)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT center_lat, center_lng, radius_meters FROM geofences WHERE is_active = 1 LIMIT 1")
    geo = cur.fetchone()
    is_violation = 0
    if geo:
        dist = haversine_distance(lat, lng, geo["center_lat"], geo["center_lng"])
        if dist > geo["radius_meters"]:
            is_violation = 1

    # 8. Guardar en Base de Datos
    cur.execute("""
    INSERT INTO telemetry (
        collar_id, timestamp, latitude, longitude, altitude, speed_kmh,
        satellites, hdop, pitch, roll, motion_index, activity,
        battery_v, battery_pct, rssi, snr, gateway_id,
        is_geofence_violation, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        collar_id, timestamp, lat, lng, alt, speed,
        sats, hdop, pitch, roll, motion, activity,
        batt_v, batt_pct, rssi, snr, gateway_id,
        is_violation, json.dumps(payload)
    ))

    final_status = "Alerta: Fuera de Zona" if is_violation else activity
    cur.execute("""
    INSERT INTO collars (collar_id, cow_name, status, last_seen, last_lat, last_lng, battery_pct, battery_v)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(collar_id) DO UPDATE SET
        status = excluded.status,
        last_seen = excluded.last_seen,
        last_lat = excluded.last_lat,
        last_lng = excluded.last_lng,
        battery_pct = excluded.battery_pct,
        battery_v = excluded.battery_v
    """, (collar_id, f"Vaca {collar_id}", final_status, timestamp, lat, lng, batt_pct, batt_v))

    # 9. Crear Alertas si amerita
    if is_violation:
        cur.execute("""
        INSERT INTO alerts (collar_id, alert_type, level, message, timestamp)
        VALUES (?, 'GEOFENCE', 'danger', ?, ?)
        """, (collar_id, f"¡ALERTA DE SEGURIDAD! El animal {collar_id} ha salido del potrero delimitado.", timestamp))

    if batt_pct < 20:
        cur.execute("""
        INSERT INTO alerts (collar_id, alert_type, level, message, timestamp)
        VALUES (?, 'BATTERY_LOW', 'warning', ?, ?)
        """, (collar_id, f"Batería baja en collar {collar_id} ({batt_pct}% - {batt_v:.2f}V). Recargar pronto.", timestamp))

    if motion > 2.0:
        cur.execute("""
        INSERT INTO alerts (collar_id, alert_type, level, message, timestamp)
        VALUES (?, 'HIGH_ACCEL', 'warning', ?, ?)
        """, (collar_id, f"Movimiento brusco o posible agitación detectada en {collar_id}.", timestamp))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": "Telemetría registrada exitosamente",
        "collar_id": collar_id,
        "activity": activity,
        "is_geofence_violation": bool(is_violation),
        "timestamp": timestamp
    }


class CowlarRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=get_static_dir(), **kwargs)

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ["/", "/index.html", "/healthz", "/style.css", "/app.js", "/favicon.ico"]:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        return super().do_HEAD()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. API: List Collars & Latest Telemetry
        if path == "/api/collars":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
            SELECT c.*, 
                   t.pitch, t.roll, t.motion_index, t.activity, 
                   t.rssi, t.snr, t.speed_kmh, t.satellites, t.gateway_id
            FROM collars c
            LEFT JOIN telemetry t ON t.id = (
                SELECT MAX(id) FROM telemetry WHERE collar_id = c.collar_id
            )
            ORDER BY c.collar_id ASC
            """)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return self.send_json({"collars": rows})

        # 2. API: Collar History
        elif path.startswith("/api/collars/") and path.endswith("/history"):
            parts = path.strip("/").split("/")
            collar_id = parts[2]
            limit = int(query.get("limit", [100])[0])
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
            SELECT id, collar_id, timestamp, latitude, longitude, altitude, 
                   speed_kmh, satellites, hdop, pitch, roll, motion_index, 
                   activity, battery_v, battery_pct, rssi, snr, is_geofence_violation
            FROM telemetry
            WHERE collar_id = ?
            ORDER BY id DESC
            LIMIT ?
            """, (collar_id, limit))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return self.send_json({"collar_id": collar_id, "history": rows})

        # 3. API: Dashboard Statistics
        elif path == "/api/dashboard/stats":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM collars")
            total_cows = cur.fetchone()[0]

            cur.execute("SELECT AVG(battery_pct) FROM collars")
            avg_batt = round(cur.fetchone()[0] or 0, 1)

            cur.execute("SELECT COUNT(*) FROM alerts WHERE is_resolved = 0")
            active_alerts = cur.fetchone()[0]

            cur.execute("""
            SELECT activity, COUNT(*) as count 
            FROM (SELECT activity FROM telemetry ORDER BY id DESC LIMIT 200)
            GROUP BY activity
            """)
            act_rows = cur.fetchall()
            activity_breakdown = {r["activity"] or "Otro": r["count"] for r in act_rows}

            conn.close()
            return self.send_json({
                "total_cows": total_cows,
                "average_battery_pct": avg_batt,
                "active_alerts_count": active_alerts,
                "activity_breakdown": activity_breakdown
            })

        # 4. API: Geofence details
        elif path == "/api/geofence":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM geofences WHERE is_active = 1 LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                d = dict(row)
                d["polygon"] = json.loads(d["polygon_json"])
                return self.send_json(d)
            return self.send_json({"error": "No active geofence"}, 404)

        # 5. API: Active Alerts
        elif path == "/api/alerts":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM alerts WHERE is_resolved = 0 ORDER BY id DESC LIMIT 50")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return self.send_json({"alerts": rows})

        # 6. API: Estado del Cliente MQTT
        elif path == "/api/mqtt/status":
            if mqtt_mgr:
                return self.send_json(mqtt_mgr.get_status())
            return self.send_json({"connected": False, "status_text": "Gestor MQTT no inicializado"})

        # 7. API: CSV Export
        elif path == "/api/export/csv":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
            SELECT t.id, t.timestamp, t.collar_id, c.cow_name, t.latitude, t.longitude,
                   t.altitude, t.speed_kmh, t.satellites, t.pitch, t.roll, t.motion_index,
                   t.activity, t.battery_v, t.battery_pct, t.rssi, t.snr, t.gateway_id,
                   t.is_geofence_violation
            FROM telemetry t
            LEFT JOIN collars c ON c.collar_id = t.collar_id
            ORDER BY t.id DESC LIMIT 1000
            """)
            rows = cur.fetchall()
            conn.close()

            csv_lines = [
                "ID;FechaHora;CollarID;NombreVaca;Latitud;Longitud;Altitud;VelocidadKmH;Satelites;InclinacionPitch;GiroRoll;IndiceMovimiento;Actividad;BateriaVoltios;BateriaPct;RSSI_dBm;SNR_dB;GatewayID;AlertaCerco"
            ]
            for r in rows:
                csv_lines.append(";".join(str(r[k] if r[k] is not None else "") for k in r.keys()))

            csv_content = "\r\n".join(csv_lines).encode("utf-8-sig")
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="Cowlar_Telemetria_Historica.csv"')
            self.send_header('Content-Length', str(len(csv_content)))
            self.end_headers()
            return self.wfile.write(csv_content)

        # Manejo explícito de archivos estáticos para la nube (Render)
        s_dir = get_static_dir()
        if path in ["/", "/index.html"]:
            idx_file = os.path.join(s_dir, "index.html")
            if os.path.exists(idx_file):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                with open(idx_file, 'rb') as f:
                    content = f.read()
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                return self.wfile.write(content)
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Cowlar</title><style>body{background:#0c120e;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;text-align:center;}div{background:#17201a;border:1px solid rgba(56,178,89,0.3);padding:30px;border-radius:14px;max-width:500px;}h2{color:#38b259;}p{color:#8ca493;line-height:1.6;}</style></head><body><div><h2>Servidor Cowlar Activo</h2><p>El servidor est&aacute; corriendo en Render, pero falta subir la carpeta <strong>static</strong> (con index.html, style.css y app.js) a tu repositorio de GitHub.</p></div></body></html>""".encode('utf-8')
                self.send_header('Content-Length', str(len(html)))
                self.end_headers()
                return self.wfile.write(html)
        elif path in ["/style.css", "/static/style.css"]:
            css_file = os.path.join(s_dir, "style.css")
            if os.path.exists(css_file):
                self.send_response(200)
                self.send_header('Content-Type', 'text/css; charset=utf-8')
                with open(css_file, 'rb') as f:
                    content = f.read()
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                return self.wfile.write(content)
        elif path in ["/app.js", "/static/app.js"]:
            js_file = os.path.join(s_dir, "app.js")
            if os.path.exists(js_file):
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                with open(js_file, 'rb') as f:
                    content = f.read()
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                return self.wfile.write(content)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # Static fallback
        if path.startswith("/static/"):
            self.path = path[7:]
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8', errors='ignore') if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        # 1. THE THINGS NETWORK (TTN) WEBHOOK / UPLINK INGESTION
        if path in ["/api/ttn/webhook", "/api/uplink"]:
            result = ingest_telemetry_payload(payload)
            return self.send_json(result)

        # 2. SIMULATION TICK
        elif path == "/api/simulate/tick":
            return self.handle_simulation_tick(payload)

        # 3. RESOLVE ALERT
        elif path.startswith("/api/alerts/") and path.endswith("/resolve"):
            parts = path.strip("/").split("/")
            alert_id = parts[2]
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE alerts SET is_resolved = 1 WHERE id = ?", (alert_id,))
            conn.commit()
            conn.close()
            return self.send_json({"status": "resolved", "id": alert_id})

        # 4. UPDATE GEOFENCE
        elif path == "/api/geofence":
            center_lat = float(payload.get("center_lat", -0.3245))
            center_lng = float(payload.get("center_lng", -78.4520))
            radius = float(payload.get("radius_meters", 70.0))
            paddock_size = float(payload.get("paddock_size_meters", 100.0))
            
            delta = (paddock_size / 2.0) / 111320.0
            polygon = [
                [center_lat + delta, center_lng - delta],
                [center_lat + delta, center_lng + delta],
                [center_lat - delta, center_lng + delta],
                [center_lat - delta, center_lng - delta],
                [center_lat + delta, center_lng - delta]
            ]
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
            UPDATE geofences 
            SET center_lat = ?, center_lng = ?, radius_meters = ?, paddock_size_meters = ?, polygon_json = ?
            WHERE is_active = 1
            """, (center_lat, center_lng, radius, paddock_size, json.dumps(polygon)))
            conn.commit()
            conn.close()
            return self.send_json({"status": "updated", "center_lat": center_lat, "center_lng": center_lng, "polygon": polygon})

        # 5. CONFIGURACIÓN MQTT
        elif path == "/api/mqtt/config":
            if mqtt_mgr:
                mqtt_mgr.update_config(payload)
                if payload.get("connect_now", False) or payload.get("enabled", False):
                    mqtt_mgr.start()
                else:
                    mqtt_mgr.stop()
                return self.send_json({"status": "saved", "mqtt": mqtt_mgr.get_status()})
            return self.send_json({"error": "MQTT no disponible"}, 500)

        elif path == "/api/mqtt/connect":
            if mqtt_mgr:
                mqtt_mgr.config["enabled"] = True
                save_config(mqtt_mgr.config)
                mqtt_mgr.start()
                return self.send_json({"status": "connecting", "mqtt": mqtt_mgr.get_status()})
            return self.send_json({"error": "MQTT no disponible"}, 500)

        elif path == "/api/mqtt/disconnect":
            if mqtt_mgr:
                mqtt_mgr.config["enabled"] = False
                save_config(mqtt_mgr.config)
                mqtt_mgr.stop()
                return self.send_json({"status": "disconnected", "mqtt": mqtt_mgr.get_status()})
            return self.send_json({"status": "disconnected"})

        return self.send_json({"error": "Endpoint not found"}, 404)

    def handle_simulation_tick(self, payload):
        collar_id = payload.get("collar_id", "COW-01")
        scenario = payload.get("scenario", "normal")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM collars WHERE collar_id = ?", (collar_id,))
        cow = cur.fetchone()
        
        cur.execute("SELECT center_lat, center_lng, radius_meters FROM geofences WHERE is_active = 1 LIMIT 1")
        geo = cur.fetchone()
        center_lat = geo["center_lat"] if geo else -0.3245
        center_lng = geo["center_lng"] if geo else -78.4520

        current_lat = cow["last_lat"] if cow and cow["last_lat"] else center_lat
        current_lng = cow["last_lng"] if cow and cow["last_lng"] else center_lng
        current_batt_v = cow["battery_v"] if cow and cow["battery_v"] else 3.98

        if scenario == "escape":
            new_lat = center_lat + 0.00110
            new_lng = center_lng + 0.00115
            pitch = -10.0
            roll = 5.0
            motion = 1.1
            activity = "Caminando"
            speed = 3.2
            batt_v = current_batt_v
        elif scenario == "low_battery":
            new_lat = current_lat + random.uniform(-0.00008, 0.00008)
            new_lng = current_lng + random.uniform(-0.00008, 0.00008)
            pitch = -5.0
            roll = 0.0
            motion = 0.05
            activity = "Reposo"
            speed = 0.0
            batt_v = 3.32
        elif scenario == "agitated":
            new_lat = current_lat + random.uniform(-0.00015, 0.00015)
            new_lng = current_lng + random.uniform(-0.00015, 0.00015)
            pitch = random.uniform(15.0, 35.0)
            roll = random.uniform(-25.0, 25.0)
            motion = 2.45
            activity = "Agitado"
            speed = 4.5
            batt_v = current_batt_v
        else: # normal
            r = random.random()
            new_lat = current_lat + random.uniform(-0.00005, 0.00005)
            new_lng = current_lng + random.uniform(-0.00005, 0.00005)
            dist_to_center = haversine_distance(new_lat, new_lng, center_lat, center_lng)
            if dist_to_center > 45:
                new_lat = center_lat + random.uniform(-0.0001, 0.0001)
                new_lng = center_lng + random.uniform(-0.0001, 0.0001)

            if r < 0.60:
                activity = "Pastando"
                pitch = random.uniform(-35.0, -22.0)
                roll = random.uniform(-8.0, 8.0)
                motion = random.uniform(0.15, 0.45)
                speed = random.uniform(0.1, 0.4)
            elif r < 0.85:
                activity = "Rumia"
                pitch = random.uniform(-15.0, 5.0)
                roll = random.uniform(-5.0, 5.0)
                motion = random.uniform(0.10, 0.28)
                speed = 0.0
            elif r < 0.95:
                activity = "Reposo"
                pitch = random.uniform(-5.0, 5.0)
                roll = random.uniform(-2.0, 2.0)
                motion = random.uniform(0.01, 0.06)
                speed = 0.0
            else:
                activity = "Caminando"
                pitch = random.uniform(-10.0, 15.0)
                roll = random.uniform(-10.0, 10.0)
                motion = random.uniform(0.65, 1.1)
                speed = random.uniform(0.8, 1.8)

            batt_v = max(3.3, current_batt_v - 0.001)

        conn.close()

        sim_payload = {
            "end_device_ids": {"device_id": collar_id.lower()},
            "uplink_message": {
                "decoded_payload": {
                    "lat": round(new_lat, 6),
                    "lng": round(new_lng, 6),
                    "alt": 2650.0 + random.uniform(-1.0, 1.0),
                    "speed": round(speed, 1),
                    "sats": random.randint(8, 11),
                    "hdop": round(random.uniform(0.9, 1.3), 1),
                    "pitch": round(pitch, 1),
                    "roll": round(roll, 1),
                    "motion": round(motion, 2),
                    "activity": activity,
                    "batt_v": round(batt_v, 2),
                    "batt_pct": int(max(0, min(100, (batt_v - 3.2) / (4.15 - 3.2) * 100)))
                },
                "rx_metadata": [{
                    "gateway_ids": {"gateway_id": "heltec-htm7603-hacienda"},
                    "rssi": random.randint(-88, -74),
                    "snr": round(random.uniform(7.5, 11.2), 1)
                }]
            }
        }
        res = ingest_telemetry_payload(sim_payload)
        return self.send_json(res)


def run_server():
    global mqtt_mgr
    init_db()

    # Inicializar cliente MQTT en segundo plano
    mqtt_mgr = TTNMqttManager(ingest_telemetry_payload)
    if mqtt_mgr.config.get("enabled", False) and mqtt_mgr.config.get("api_key"):
        print("[MQTT] Iniciando conexión automática con The Things Network...")
        mqtt_mgr.start()

    socketserver.TCPServer.allow_reuse_address = True
    server_address = ('', PORT)
    with socketserver.ThreadingTCPServer(server_address, CowlarRequestHandler) as httpd:
        print("================================================================")
        print("  COWLAR - Servidor Web & Ingesta TTN (MQTT + Webhook)")
        print(f"  Dashboard Web:   http://localhost:{PORT}")
        print(f"  Cliente MQTT:    Conexión nativa a nam1.cloud.thethings.network")
        print(f"  Webhook TTN URL: http://localhost:{PORT}/api/ttn/webhook")
        print("================================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDeteniendo servidor Cowlar...")
            if mqtt_mgr:
                mqtt_mgr.stop()
            print("Servidor cerrado.")

if __name__ == "__main__":
    run_server()
