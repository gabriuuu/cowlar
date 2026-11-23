import sqlite3
import json
import os
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "cowlar.db")

# Timezone Ecuador (UTC-5)
ECUADOR_TZ = timezone(timedelta(hours=-5))

def now_iso():
    return datetime.now(ECUADOR_TZ).strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Collars / Cows Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS collars (
        collar_id TEXT PRIMARY KEY,
        cow_name TEXT NOT NULL,
        earring_number TEXT,
        breed TEXT,
        age_months INTEGER,
        weight_kg REAL,
        status TEXT DEFAULT 'Pastando',
        last_seen TEXT,
        last_lat REAL,
        last_lng REAL,
        battery_pct INTEGER DEFAULT 100,
        battery_v REAL DEFAULT 4.10,
        color TEXT DEFAULT '#22c55e'
    )
    """)
    
    # 2. Telemetry Log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        collar_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        altitude REAL,
        speed_kmh REAL,
        satellites INTEGER,
        hdop REAL,
        pitch REAL,
        roll REAL,
        motion_index REAL,
        activity TEXT,
        battery_v REAL,
        battery_pct INTEGER,
        rssi INTEGER,
        snr REAL,
        gateway_id TEXT,
        is_geofence_violation INTEGER DEFAULT 0,
        raw_json TEXT
    )
    """)
    
    # 3. Geofences (100x100m pasture or custom zones)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS geofences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        center_lat REAL NOT NULL,
        center_lng REAL NOT NULL,
        radius_meters REAL DEFAULT 70,
        paddock_size_meters REAL DEFAULT 100,
        polygon_json TEXT,
        is_active INTEGER DEFAULT 1
    )
    """)
    
    # 4. Alerts
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        collar_id TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        level TEXT DEFAULT 'warning',
        message TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        is_resolved INTEGER DEFAULT 0
    )
    """)
    
    # Populate initial default data if empty
    cur.execute("SELECT COUNT(*) FROM collars")
    if cur.fetchone()[0] == 0:
        # Default Hacienda in Ecuador (Pichincha / Mejia / Valle de los Chillos farm coordinates as reference, -0.3245, -78.4520)
        base_lat = -0.324500
        base_lng = -78.452000
        
        cows = [
            ("COW-01", "Manuela #104", "EC-104", "Holstein Mestiza", 36, 480.0, "Pastando", now_iso(), base_lat + 0.00015, base_lng + 0.00010, 88, 3.98, "#10b981"),
            ("COW-02", "Esperanza #108", "EC-108", "Brown Swiss", 42, 510.0, "Rumia", now_iso(), base_lat - 0.00018, base_lng + 0.00025, 76, 3.84, "#3b82f6"),
            ("COW-03", "Paloma #112", "EC-112", "Girolando", 28, 430.0, "Reposo", now_iso(), base_lat + 0.00022, base_lng - 0.00020, 94, 4.12, "#8b5cf6")
        ]
        cur.executemany("""
        INSERT INTO collars (collar_id, cow_name, earring_number, breed, age_months, weight_kg, status, last_seen, last_lat, last_lng, battery_pct, battery_v, color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, cows)
        
        # Default 100x100m pasture (approx +/- 0.00045 degrees lat/lng in Ecuador ~ 100m)
        delta = 0.00045
        coords = [
            [base_lat + delta, base_lng - delta],
            [base_lat + delta, base_lng + delta],
            [base_lat - delta, base_lng + delta],
            [base_lat - delta, base_lng - delta],
            [base_lat + delta, base_lng - delta]
        ]
        cur.execute("""
        INSERT INTO geofences (name, center_lat, center_lng, radius_meters, paddock_size_meters, polygon_json, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("Potrero Principal (100 x 100 m)", base_lat, base_lng, 70, 100, json.dumps(coords), 1))
        
        # Initial telemetry history points for COW-01
        telemetry_samples = [
            ("COW-01", now_iso(), base_lat + 0.00015, base_lng + 0.00010, 2650.0, 0.4, 9, 1.1, -38.5, 3.2, 0.45, "Pastando", 3.98, 88, -82, 9.5, "dragino-lps8n-hacienda", 0),
            ("COW-01", now_iso(), base_lat + 0.00012, base_lng + 0.00008, 2650.2, 0.2, 8, 1.2, -42.0, 1.1, 0.38, "Pastando", 3.98, 88, -84, 9.1, "dragino-lps8n-hacienda", 0),
            ("COW-01", now_iso(), base_lat + 0.00005, base_lng + 0.00002, 2650.0, 0.8, 9, 1.1, -12.0, -2.5, 0.82, "Caminando", 3.99, 89, -80, 10.2, "dragino-lps8n-hacienda", 0),
            ("COW-02", now_iso(), base_lat - 0.00018, base_lng + 0.00025, 2649.5, 0.1, 8, 1.3, -5.4, 12.0, 0.15, "Rumia", 3.84, 76, -88, 8.4, "dragino-lps8n-hacienda", 0),
            ("COW-03", now_iso(), base_lat + 0.00022, base_lng - 0.00020, 2650.5, 0.0, 10, 0.9, 2.1, 4.0, 0.05, "Reposo", 4.12, 94, -75, 11.0, "dragino-lps8n-hacienda", 0)
        ]
        cur.executemany("""
        INSERT INTO telemetry (collar_id, timestamp, latitude, longitude, altitude, speed_kmh, satellites, hdop, pitch, roll, motion_index, activity, battery_v, battery_pct, rssi, snr, gateway_id, is_geofence_violation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, telemetry_samples)
        
        # Initial Welcome Alert
        cur.execute("""
        INSERT INTO alerts (collar_id, alert_type, level, message, timestamp, is_resolved)
        VALUES (?, ?, ?, ?, ?, ?)
        """, ("SISTEMA", "INFO", "info", "Sistema Cowlar iniciado. Esperando tramas LoRaWAN desde Gateway Dragino / TTN.", now_iso(), 1))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
