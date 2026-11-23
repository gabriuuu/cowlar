"""
=====================================================================================
  PROYECTO DE GRADO: COWLAR — CLIENTE MQTT NATIVO PARA THE THINGS NETWORK (TTN)
  Protocolo: MQTT 3.1.1 sobre TLS (Puerto 8883) o TCP (Puerto 1883)
  Biblioteca estándar de Python: socket, ssl, struct, threading, json
  ¡Cero dependencias externas (no requiere pip ni herramientas de túnel como ngrok)!
=====================================================================================
"""

import socket
import ssl
import struct
import json
import threading
import time
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "mqtt_config.json")

DEFAULT_CONFIG = {
    "enabled": False,
    "broker": "nam1.cloud.thethings.network",
    "port": 8883,
    "use_tls": True,
    "app_id": "cowlar-ganado-uets",
    "api_key": "",
    "topic": "v3/+/devices/+/up"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                merged = dict(DEFAULT_CONFIG)
                merged.update(cfg)
                return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MQTT] Error guardando configuración: {e}")
        return False

class PureMqttClient:
    """
    Cliente MQTT 3.1.1 ligero implementado únicamente con sockets y ssl estándar.
    """
    def __init__(self, host, port=8883, use_tls=True, username="", password="", client_id="cowlar-uets-listener"):
        self.host = host
        self.port = int(port)
        self.use_tls = use_tls
        self.username = username
        self.password = password
        self.client_id = client_id
        self.sock = None
        self.connected = False
        self.running = False
        self.on_message = None
        self._packet_id = 1
        self._last_ping = 0

    def _encode_string(self, s):
        data = s.encode('utf-8')
        return struct.pack("!H", len(data)) + data

    def _encode_remaining_len(self, length):
        res = bytearray()
        while True:
            b = length % 128
            length = length // 128
            if length > 0:
                b |= 0x80
            res.append(b)
            if length == 0:
                break
        return bytes(res)

    def _read_exact(self, n):
        chunks = []
        bytes_recd = 0
        while bytes_recd < n:
            chunk = self.sock.recv(min(n - bytes_recd, 4096))
            if not chunk:
                raise ConnectionError("Conexión cerrada por el broker MQTT")
            chunks.append(chunk)
            bytes_recd += len(chunk)
        return b''.join(chunks)

    def _decode_remaining_len(self):
        multiplier = 1
        value = 0
        while True:
            b = self._read_exact(1)[0]
            value += (b & 127) * multiplier
            if (b & 128) == 0:
                break
            multiplier *= 128
        return value

    def _send_packet(self, packet_bytes):
        if self.sock:
            self.sock.sendall(packet_bytes)

    def connect(self):
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(12.0)
        
        if self.use_tls:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
        else:
            self.sock = raw_sock
        
        self.sock.connect((self.host, self.port))
        
        # CONNECT Packet MQTT 3.1.1
        var_hdr = (
            self._encode_string("MQTT") +
            b'\x04' +               # Protocol Level 4
            b'\xc2' +               # Flags: Username, Password, Clean Session
            struct.pack("!H", 60)   # Keep Alive: 60s
        )
        payload = (
            self._encode_string(self.client_id) +
            self._encode_string(self.username) +
            self._encode_string(self.password)
        )
        pkt = b'\x10' + self._encode_remaining_len(len(var_hdr) + len(payload)) + var_hdr + payload
        self._send_packet(pkt)
        
        # Read CONNACK
        header = self._read_exact(1)
        if header[0] >> 4 != 2:
            raise ConnectionError(f"Respuesta inesperada al conectar: {header[0]:#x}")
        rem_len = self._decode_remaining_len()
        connack_body = self._read_exact(rem_len)
        return_code = connack_body[1]
        if return_code != 0:
            error_map = {
                1: "Versión de protocolo no aceptada",
                2: "Identificador de cliente rechazado",
                3: "Servidor TTN no disponible temporalmente",
                4: "Credenciales incorrectas (Usuario o API Key inválida)",
                5: "No autorizado para acceder a esta aplicación"
            }
            raise ConnectionRefusedError(error_map.get(return_code, f"Error {return_code}"))

        self.connected = True
        self.running = True
        self._last_ping = time.time()
        return True

    def subscribe(self, topic, qos=0):
        self._packet_id = (self._packet_id + 1) % 65535 or 1
        var_hdr = struct.pack("!H", self._packet_id)
        payload = self._encode_string(topic) + bytes([qos])
        pkt = b'\x82' + self._encode_remaining_len(len(var_hdr) + len(payload)) + var_hdr + payload
        self._send_packet(pkt)

    def ping(self):
        self._send_packet(b'\xc0\x00')
        self._last_ping = time.time()

    def disconnect(self):
        self.running = False
        self.connected = False
        try:
            if self.sock:
                self._send_packet(b'\xe0\x00')
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def receive_packet(self):
        header_byte = self._read_exact(1)[0]
        pkt_type = header_byte >> 4
        flags = header_byte & 0x0F
        rem_len = self._decode_remaining_len()
        body = self._read_exact(rem_len) if rem_len > 0 else b''

        # PUBLISH (3)
        if pkt_type == 3:
            topic_len = struct.unpack("!H", body[0:2])[0]
            topic = body[2:2+topic_len].decode('utf-8', errors='ignore')
            offset = 2 + topic_len
            qos = (flags >> 1) & 0x03
            if qos > 0:
                offset += 2 # Saltar packet_id
            payload_str = body[offset:].decode('utf-8', errors='ignore')
            try:
                data = json.loads(payload_str)
            except Exception:
                data = {"raw_text": payload_str}
            if self.on_message:
                self.on_message(topic, data)

        # PINGRESP (13)
        elif pkt_type == 13:
            pass

        return pkt_type


class TTNMqttManager:
    """
    Administrador del hilo de fondo para la conexión MQTT con The Things Network.
    """
    def __init__(self, telemetry_callback):
        self.telemetry_callback = telemetry_callback
        self.config = load_config()
        self.client = None
        self.thread = None
        self.is_running = False
        self.status = {
            "connected": False,
            "status_text": "Desconectado",
            "messages_count": 0,
            "last_message_time": None,
            "last_error": None,
            "broker": self.config.get("broker", "nam1.cloud.thethings.network"),
            "app_id": self.config.get("app_id", "cowlar-ganado-uets")
        }

    def get_status(self):
        s = dict(self.status)
        s["enabled"] = self.config.get("enabled", False)
        s["broker"] = self.config.get("broker", "nam1.cloud.thethings.network")
        s["port"] = self.config.get("port", 8883)
        s["app_id"] = self.config.get("app_id", "cowlar-ganado-uets")
        s["has_key"] = bool(self.config.get("api_key", "").strip())
        return s

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False
        if self.client:
            self.client.disconnect()
        self.status["connected"] = False
        self.status["status_text"] = "Desconectado"

    def update_config(self, new_cfg):
        self.config.update(new_cfg)
        save_config(self.config)
        # Si se cambió la clave o broker, reconectar
        if self.is_running:
            self.stop()
            time.sleep(0.5)
            self.start()

    def _run_loop(self):
        while self.is_running:
            api_key = self.config.get("api_key", "").strip()
            app_id = self.config.get("app_id", "cowlar-ganado-uets").strip()
            broker = self.config.get("broker", "nam1.cloud.thethings.network").strip()
            port = int(self.config.get("port", 8883))
            use_tls = (port == 8883) or self.config.get("use_tls", True)

            if not api_key:
                self.status["connected"] = False
                self.status["status_text"] = "Esperando API Key de TTN"
                time.sleep(2)
                continue

            username = f"{app_id}@ttn"
            client_id = f"cowlar-app-{int(time.time()) % 10000}"
            self.status["status_text"] = f"Conectando a {broker}:{port}..."

            try:
                self.client = PureMqttClient(
                    host=broker,
                    port=port,
                    use_tls=use_tls,
                    username=username,
                    password=api_key,
                    client_id=client_id
                )
                self.client.on_message = self._handle_mqtt_message

                self.client.connect()
                self.status["connected"] = True
                self.status["status_text"] = "🟢 Conectado en vivo a The Things Network"
                self.status["last_error"] = None
                print(f"[MQTT] Conectado exitosamente a TTN ({broker}). Suscribiendo a telemetría...")

                # Suscribir a todos los dispositivos de la aplicación
                topic = f"v3/{username}/devices/+/up"
                self.client.subscribe(topic)
                print(f"[MQTT] Suscrito a topic: {topic}")

                last_ping_check = time.time()
                while self.is_running and self.client.connected:
                    self.client.receive_packet()
                    # Enviar Ping cada 30 segundos
                    if time.time() - last_ping_check > 30:
                        self.client.ping()
                        last_ping_check = time.time()

            except Exception as e:
                err_msg = str(e)
                print(f"[MQTT] Advertencia/Error de conexión: {err_msg}")
                self.status["connected"] = False
                self.status["status_text"] = f"Reintentando conexión ({err_msg})"
                self.status["last_error"] = err_msg
                if self.client:
                    self.client.disconnect()
                time.sleep(5)

        self.status["connected"] = False
        self.status["status_text"] = "Desconectado"

    def _handle_mqtt_message(self, topic, data):
        self.status["messages_count"] += 1
        self.status["last_message_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[MQTT 📡] Mensaje LoRa recibido desde TTN ({topic})")
        if self.telemetry_callback:
            try:
                self.telemetry_callback(data)
            except Exception as e:
                print(f"[MQTT] Error procesando telemetría en Cowlar: {e}")
