// Cowlar v2.0 — Frontend Application Logic
// Proyecto de Grado UETS · Nova Green · Ecuador 2026-2027

// ============================================================
// SISTEMA DE TOASTS (reemplaza alert/confirm)
// ============================================================
function showToast(msg, type = 'info', title = '', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const titles = { success: 'Éxito', error: 'Error', warning: 'Advertencia', info: 'Información' };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'alert');
  toast.innerHTML = `
    <span class="toast-icon" aria-hidden="true">${icons[type] || 'ℹ️'}</span>
    <div class="toast-body">
      <div class="toast-title">${title || titles[type] || ''}</div>
      <div class="toast-msg">${msg}</div>
    </div>
    <button class="toast-close" aria-label="Cerrar notificación" onclick="removeToast(this.parentElement)">×</button>
  `;

  container.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => removeToast(toast), duration);
  }
  return toast;
}

function removeToast(el) {
  if (!el || el.classList.contains('removing')) return;
  el.classList.add('removing');
  el.addEventListener('animationend', () => el.remove(), { once: true });
}

let map;
let baseTileLayer;
let satelliteTileLayer;
let isSatellite = false;
let geofencePolygon;
let cowMarkers = {};
let cowBreadcrumb;
let selectedCollarId = "COW-01";
let collarsData = [];
let simInterval = null;
let isSimulating = false;

// Charts
let chartDonut = null;
let chartTimeline = null;

// Audio context for alerts
let audioCtx = null;

function playAlertBeep() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
    osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.3);
    gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.3);
  } catch (e) {
    console.log("Audio alert suppressed or unavailable:", e);
  }
}

// 1. INITIALIZATION
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initMap();
  loadGeofence();
  loadCollars();
  loadDashboardStats();
  loadTelemetryHistory();
  initCharts();
  loadMqttStatus();

  // Polling loop every 3.5 seconds
  setInterval(() => {
    loadCollars(false);
    loadDashboardStats();
    loadMqttStatus();
    if (document.getElementById("tab-history").classList.contains("active")) {
      loadTelemetryHistory();
    }
  }, 3500);
});

// ── Reloj ──
function initClock() {
  const el = document.getElementById("clock-display");
  const update = () => {
    const d = new Date();
    el.textContent = d.toLocaleTimeString('es-EC', { hour12: false });
  };
  update();
  setInterval(update, 1000);
}

// ── Estado del header ──
function updateHeaderStatus(mqttConnected) {
  const ttnEl = document.getElementById('ttn-status-text');
  const gwEl  = document.getElementById('gateway-status-text');
  const dot   = document.getElementById('gateway-dot');

  if (ttnEl) {
    ttnEl.textContent = mqttConnected ? 'Conectado' : 'Desconectado';
    ttnEl.style.color = mqttConnected ? 'var(--color-grazing)' : 'var(--text-muted)';
  }
  if (gwEl && dot) {
    gwEl.textContent = 'HT-M7603 En Línea';
    gwEl.style.color = 'var(--color-grazing)';
    dot.style.background = 'var(--color-grazing)';
  }
}

// Tab Switching (Compatible con navegación desktop y barra móvil)
function switchTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".mobile-nav-item").forEach(b => b.classList.remove("active"));

  const targetPane = document.getElementById(tabId);
  if (targetPane) targetPane.classList.add("active");

  document.querySelectorAll(".tab-btn, .mobile-nav-item").forEach(b => {
    const oc = b.getAttribute("onclick") || "";
    if (oc.includes(tabId)) {
      b.classList.add("active");
    }
  });

  if (tabId === "tab-dashboard" && map) {
    setTimeout(() => map.invalidateSize(), 150);
  } else if (tabId === "tab-behavior") {
    setTimeout(() => updateBehaviorCharts(), 150);
  } else if (tabId === "tab-history") {
    loadTelemetryHistory();
  }
}

// 2. LEAFLET MAP INITIALIZATION
function initMap() {
  // Default coordinates: Farm in Ecuador (-0.3245, -78.4520)
  const defaultCenter = [-0.3245, -78.4520];

  map = L.map("map", {
    zoomControl: true,
    attributionControl: false
  }).setView(defaultCenter, 18);

  // Standard OpenStreetMap layer
  baseTileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19
  }).addTo(map);

  // ESRI World Imagery (Satellite)
  satelliteTileLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19
  });

  // Breadcrumbs line
  cowBreadcrumb = L.polyline([], {
    color: '#4EBE6A',
    weight: 2.5,
    dashArray: '4, 4',
    opacity: 0.85
  }).addTo(map);
}

function toggleMapLayer() {
  if (isSatellite) {
    map.removeLayer(satelliteTileLayer);
    map.addLayer(baseTileLayer);
    isSatellite = false;
  } else {
    map.removeLayer(baseTileLayer);
    map.addLayer(satelliteTileLayer);
    isSatellite = true;
  }
}

function loadGeofence() {
  fetch("/api/geofence")
    .then(r => r.json())
    .then(geo => {
      if (geo && geo.polygon) {
        if (geofencePolygon) map.removeLayer(geofencePolygon);

        geofencePolygon = L.polygon(geo.polygon, {
          color: '#4EBE6A',
          weight: 1.5,
          fillColor: '#4EBE6A',
          fillOpacity: 0.08,
          dashArray: '6, 6'
        }).addTo(map);

        geofencePolygon.bindPopup(`<b>${geo.name}</b><br>Perímetro de seguridad: 100 x 100 m.`);
      }
    })
    .catch(err => console.error("Error loading geofence:", err));
}

// 3. COLLARS & TELEMETRY LOADING
function loadCollars(centerMap = true) {
  fetch("/api/collars")
    .then(r => r.json())
    .then(data => {
      collarsData = data.collars || [];
      renderCowSelectorPills();
      updateMapMarkers(centerMap);
      updateSelectedCowDetail();
      checkForAlerts();
    })
    .catch(err => console.error("Error loading collars:", err));
}

function renderCowSelectorPills() {
  const bar = document.getElementById("cow-selector-bar");
  if (!bar) return;

  bar.innerHTML = collarsData.map(c => {
    const isAct = c.collar_id === selectedCollarId ? "active" : "";
    const isAlert = c.status && c.status.toLowerCase().includes("alerta");
    const dotColor = isAlert ? "var(--color-alert)" : (c.status === "Pastando" ? "var(--color-grazing)" : (c.status === "Rumia" ? "var(--color-rumination)" : "var(--color-resting)"));
    const statusText = isAlert ? "¡Fuera de cerca!" : (c.status || "Pastando");
    const icon = isAlert ? "🚨" : (c.status === "Pastando" ? "🌿" : (c.status === "Rumia" ? "🐮" : "💤"));
    return `
      <div class="cow-select-pill ${isAct}" onclick="selectCollar('${c.collar_id}')" role="button" tabindex="0">
        <span class="pill-avatar">${icon}</span>
        <div class="pill-info">
          <span class="pill-name">${c.cow_name || ('Vaca ' + c.collar_id)}</span>
          <span class="pill-status"><span class="pill-status-dot" style="background:${dotColor};"></span> ${statusText}</span>
        </div>
        <span class="pill-battery">🔋 ${c.battery_pct || 85}%</span>
      </div>
    `;
  }).join("");
}

function selectCollar(collarId) {
  selectedCollarId = collarId;
  renderCowSelectorPills();
  updateSelectedCowDetail();
  loadCollarHistoryPath(collarId);
  centerMapOnCurrentCow();
}

function updateMapMarkers(initialCenter) {
  let selectedCoord = null;

  collarsData.forEach(cow => {
    if (!cow.last_lat || !cow.last_lng) return;

    const latLng = [cow.last_lat, cow.last_lng];
    const isSel = cow.collar_id === selectedCollarId;
    if (isSel) selectedCoord = latLng;

    const isAlert = cow.status && cow.status.toLowerCase().includes("alerta");
    const markerColor = isAlert ? "var(--color-alert)" : (cow.color || "var(--color-grazing)");

    // Custom Minimalist Tracker Marker Icon
    const customIcon = L.divIcon({
      className: "custom-cow-pin",
      html: `
        <div class="map-tracker-pin ${isSel ? 'selected' : ''}">
          <div class="pin-tag-badge" style="background:${markerColor};">
            ${cow.collar_id} · ${cow.status || "Pastando"}
          </div>
          <div class="pin-marker-core" style="border-color:${markerColor};">
            🐮
          </div>
        </div>
      `,
      iconSize: [36, 50],
      iconAnchor: [18, 50]
    });

    if (cowMarkers[cow.collar_id]) {
      cowMarkers[cow.collar_id].setLatLng(latLng);
      cowMarkers[cow.collar_id].setIcon(customIcon);
    } else {
      const marker = L.marker(latLng, { icon: customIcon }).addTo(map);
      marker.on("click", () => selectCollar(cow.collar_id));
      cowMarkers[cow.collar_id] = marker;
    }
  });

  if (initialCenter && selectedCoord) {
    map.panTo(selectedCoord);
    loadCollarHistoryPath(selectedCollarId);
  }
}

function loadCollarHistoryPath(collarId) {
  fetch(`/api/collars/${collarId}/history?limit=30`)
    .then(r => r.json())
    .then(data => {
      if (data && data.history) {
        const coords = data.history.map(h => [h.latitude, h.longitude]);
        cowBreadcrumb.setLatLngs(coords);
      }
    })
    .catch(e => console.error("Error loading path:", e));
}

function centerMapOnCurrentCow() {
  const current = collarsData.find(c => c.collar_id === selectedCollarId);
  if (current && current.last_lat && current.last_lng) {
    map.flyTo([current.last_lat, current.last_lng], 18, { duration: 0.8 });
  }
}

// 4. SELECTED COW DETAIL WIDGETS
function updateSelectedCowDetail() {
  const cow = collarsData.find(c => c.collar_id === selectedCollarId) || collarsData[0];
  if (!cow) return;

  // Header info
  document.getElementById("card-cow-name").textContent = cow.cow_name || `Vaca ${cow.collar_id}`;
  document.getElementById("card-cow-details").textContent = `Arete: ${cow.earring_number || 'EC-104'} · ${cow.breed || 'Holstein Mestiza'} · ${cow.weight_kg || 480} kg`;
  document.getElementById("card-last-seen").textContent = `Última señal: ${cow.last_seen || 'Hace unos segundos'}`;

  // Badge
  const badgeEl = document.getElementById("card-cow-badge");
  const status = cow.status || "Pastando";
  badgeEl.textContent = status;
  badgeEl.className = "activity-badge-large " + getActivityBadgeClass(status);

  // MPU-6050 Posture
  const pitch = (cow.pitch !== undefined && cow.pitch !== null) ? cow.pitch : -35.0;
  const roll = (cow.roll !== undefined && cow.roll !== null) ? cow.roll : 2.0;
  const motion = (cow.motion_index !== undefined && cow.motion_index !== null) ? cow.motion_index : 0.40;

  let pitchDesc = "(Cabeza normal)";
  if (pitch <= -22) pitchDesc = "(Comiendo pasto)";
  else if (pitch > 10) pitchDesc = "(Cabeza erguida / Alerta)";
  document.getElementById("metric-pitch").textContent = `${pitch.toFixed(1)}° ${pitchDesc}`;
  document.getElementById("metric-roll").textContent = `${roll > 0 ? '+' : ''}${roll.toFixed(1)}° (Nivelada)`;
  document.getElementById("metric-motion").textContent = `${motion.toFixed(2)} g (${motion > 0.7 ? 'Caminando' : 'Tranquila'})`;

  // Rotate cow head & horizon graphic
  const cowHead = document.getElementById("cow-head-icon");
  const horizon = document.getElementById("horizon-line");
  if (cowHead) cowHead.style.transform = `rotate(${pitch * 0.7}deg)`;
  if (horizon) horizon.style.transform = `rotate(${-roll}deg) translateY(${pitch * 0.5}px)`;

  // Battery
  const battV = cow.battery_v || 3.95;
  const battPct = cow.battery_pct !== undefined ? cow.battery_pct : Math.round((battV - 3.2) / (4.15 - 3.2) * 100);
  document.getElementById("metric-batt-v").textContent = `${battV.toFixed(2)} V`;
  document.getElementById("metric-batt-pct").textContent = `${battPct}% Disponible`;
  
  const fillEl = document.getElementById("battery-bar-fill");
  if (fillEl) {
    fillEl.style.width = `${Math.max(5, Math.min(100, battPct))}%`;
    if (battPct < 20) fillEl.style.background = "var(--color-alert)";
    else if (battPct < 45) fillEl.style.background = "var(--color-rumination)";
    else fillEl.style.background = "linear-gradient(90deg, #4EBE6A 0%, #7EBA45 100%)";
  }

  // RF and GPS
  document.getElementById("metric-rssi").textContent = `${cow.rssi || -82} dBm`;
  document.getElementById("metric-snr").textContent = `${cow.snr ? (cow.snr > 0 ? '+' : '') + cow.snr : '+9.5'} dB`;
  document.getElementById("metric-sats").textContent = `${cow.satellites || 9} Satélites`;
  document.getElementById("metric-gateway").textContent = cow.gateway_id || "Heltec HT-M7603";
}

function getActivityBadgeClass(status) {
  const s = (status || "").toLowerCase();
  if (s.includes("alerta") || s.includes("fuera") || s.includes("agitado")) return "badge-alert";
  if (s.includes("past")) return "badge-grazing";
  if (s.includes("rum")) return "badge-rumination";
  if (s.includes("repos")) return "badge-resting";
  return "badge-walking";
}

// 5. DASHBOARD STATS & ALERTS
function loadDashboardStats() {
  fetch("/api/dashboard/stats")
    .then(r => r.json())
    .then(data => {
      document.getElementById("kpi-total-cows").textContent = data.total_cows || 3;
      document.getElementById("kpi-avg-battery").textContent = `${data.average_battery_pct || 86}%`;
      
      const breakdown = data.activity_breakdown || {};
      const topAct = Object.keys(breakdown).reduce((a, b) => breakdown[a] > breakdown[b] ? a : b, "Pastando");
      document.getElementById("kpi-top-activity").textContent = `${topAct}`;

      updateDonutChartData(breakdown);
    })
    .catch(e => console.error("Error loading stats:", e));
}

function checkForAlerts() {
  fetch("/api/alerts?limit=5")
    .then(r => r.json())
    .then(data => {
      const active = (data.alerts || []).filter(a => a.is_resolved === 0);
      const banner = document.getElementById("alert-banner");
      if (active.length > 0) {
        const top = active[0];
        document.getElementById("alert-title").textContent = `¡ALERTA: ${top.alert_type}!`;
        document.getElementById("alert-desc").textContent = top.message;
        banner.style.display = "flex";
        playAlertBeep();
      } else {
        banner.style.display = "none";
      }
    })
    .catch(e => console.error("Error loading alerts:", e));
}

function dismissAlertBanner() {
  fetch("/api/alerts?limit=5")
    .then(r => r.json())
    .then(data => {
      const active = (data.alerts || []).filter(a => a.is_resolved === 0);
      active.forEach(a => {
        fetch(`/api/alerts/${a.id}/resolve`, { method: "POST" });
      });
      document.getElementById("alert-banner").style.display = "none";
    });
}

// 6. TELEMETRY TABLE
function loadTelemetryHistory() {
  fetch("/api/collars/COW-01/history?limit=25")
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById("telemetry-table-body");
      if (!tbody) return;

      const rows = data.history || [];
      tbody.innerHTML = rows.map(r => {
        const isViol = r.is_geofence_violation === 1;
        const statusBadge = isViol ? 
          `<span style="color:#ef4444; font-weight:700;">⚠️ Fuera de Potrero</span>` : 
          `<span style="color:#10b981; font-weight:600;">✅ En Rango</span>`;

        return `
          <tr>
            <td>${r.timestamp}</td>
            <td><strong>${r.collar_id}</strong></td>
            <td>Manuela #104</td>
            <td><code>${r.latitude ? r.latitude.toFixed(6) : '-'}</code></td>
            <td><code>${r.longitude ? r.longitude.toFixed(6) : '-'}</code></td>
            <td><span class="activity-badge-large ${getActivityBadgeClass(r.activity)}" style="font-size:11px; padding:2px 8px;">${r.activity}</span></td>
            <td>${r.pitch ? r.pitch.toFixed(1) : '-'}° / ${r.roll ? r.roll.toFixed(1) : '-'}°</td>
            <td><strong>${r.battery_pct}%</strong> (${r.battery_v ? r.battery_v.toFixed(2) : '-'}V)</td>
            <td>${r.rssi} dBm / ${r.snr} dB</td>
            <td>${statusBadge}</td>
          </tr>
        `;
      }).join("");

      updateTimelineChart(rows);
    })
    .catch(e => console.error("Error loading history table:", e));
}

// 7. CHARTS (CHART.JS)
function initCharts() {
  const ctxDonut = document.getElementById("chart-behavior-donut");
  if (ctxDonut) {
    chartDonut = new Chart(ctxDonut, {
      type: "doughnut",
      data: {
        labels: ["Pastando", "Rumia", "Reposo", "Caminando", "Agitado"],
        datasets: [{
          data: [55, 25, 12, 6, 2],
          backgroundColor: ["#4EBE6A", "#E88929", "#B08968", "#7EBA45", "#E5533D"],
          borderColor: "#161c18",
          borderWidth: 3,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: { color: "#c2cec6", font: { size: 12, family: "system-ui, -apple-system" }, padding: 14 }
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.label}: ${ctx.parsed}%`
            }
          }
        },
        animation: { animateScale: true, duration: 500 }
      }
    });
    window.cowlarChartDonut = chartDonut;
  }

  const ctxTimeline = document.getElementById("chart-pitch-timeline");
  if (ctxTimeline) {
    chartTimeline = new Chart(ctxTimeline, {
      type: "line",
      data: {
        labels: ["T-10","T-9","T-8","T-7","T-6","T-5","T-4","T-3","T-2","T-1","Actual"],
        datasets: [{
          label: "Inclinación Cuello Pitch (°)",
          data: [-35,-38,-42,-40,-32,-15,-10,-35,-38,-41,-38],
          borderColor: "#4EBE6A",
          backgroundColor: "rgba(78, 190, 106, 0.08)",
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          pointBackgroundColor: "#4EBE6A",
          pointBorderColor: "#161c18",
          pointBorderWidth: 1.5,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: -55, max: 20,
            grid:  { color: "rgba(255,255,255,0.04)" },
            ticks: { color: "#7a8c81", callback: v => v + "°", font: { size: 11 } }
          },
          x: {
            grid:  { color: "rgba(255,255,255,0.03)" },
            ticks: { color: "#7a8c81", font: { size: 11 } }
          }
        },
        plugins: {
          legend: { labels: { color: "#c2cec6", font: { size: 12 } } },
          tooltip: {
            callbacks: { label: ctx => ` Pitch: ${ctx.parsed.y.toFixed(1)}°` }
          }
        },
        animation: { duration: 350 }
      }
    });
  }
}

function updateDonutChartData(breakdown) {
  if (!chartDonut) return;
  const labels = ["Pastando", "Rumia", "Reposo", "Caminando", "Agitado"];
  const values = labels.map(l => breakdown[l] || 0);
  chartDonut.data.datasets[0].data = values;
  chartDonut.update();
}

function updateTimelineChart(historyRows) {
  if (!chartTimeline || !historyRows || historyRows.length === 0) return;
  const recent = [...historyRows].slice(0, 15).reverse();
  chartTimeline.data.labels = recent.map(r => r.timestamp ? r.timestamp.split(" ")[1] : "");
  chartTimeline.data.datasets[0].data = recent.map(r => r.pitch !== null ? r.pitch : -30);
  chartTimeline.update();
}

function updateBehaviorCharts() {
  if (chartDonut) chartDonut.resize();
  if (chartTimeline) chartTimeline.resize();
}

// 8. SIMULATOR & FIELD TESTING
function toggleSimulation() {
  if (isSimulating) {
    clearInterval(simInterval);
    isSimulating = false;
    document.getElementById("sim-text").textContent = "Iniciar Simulación en Vivo";
    document.getElementById("sim-icon").textContent = "▶️";
    document.getElementById("sim-status-label").textContent = "Estado: En pausa";
    document.getElementById("sim-btn-inner").textContent = "▶️ Iniciar Simulación Automática (Cada 4 seg)";
  } else {
    isSimulating = true;
    document.getElementById("sim-text").textContent = "Pausar Simulación";
    document.getElementById("sim-icon").textContent = "⏸️";
    document.getElementById("sim-status-label").textContent = "Estado: Transmitiendo cada 4 segundos...";
    document.getElementById("sim-btn-inner").textContent = "⏸️ Pausar Simulación";
    
    // Immediate step, then interval
    triggerScenario('normal');
    simInterval = setInterval(() => {
      triggerScenario('normal');
    }, 4000);
  }
}

function triggerScenario(scenario) {
  fetch("/api/simulate/tick", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      collar_id: selectedCollarId,
      scenario: scenario
    })
  })
  .then(r => r.json())
  .then(res => {
    loadCollars(false);
    loadCollarHistoryPath(selectedCollarId);
    if (scenario === "escape") {
      playAlertBeep();
      centerMapOnCurrentCow();
    }
  })
  .catch(err => console.error("Sim error:", err));
}

function sendManualUplink() {
  const jsonText = document.getElementById("manual-json-input").value;
  const statusEl = document.getElementById("manual-send-status");
  try {
    const payload = JSON.parse(jsonText);
    fetch("/api/ttn/webhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(res => {
      statusEl.textContent = `✅ Trama procesada correctamente (${res.timestamp})`;
      statusEl.style.color = '#A7C957';
      showToast('Trama inyectada y procesada. El mapa y los datos se actualizarán.', 'success', 'Trama enviada');
      loadCollars(false);
      loadCollarHistoryPath(selectedCollarId);
    })
    .catch(e => {
      statusEl.textContent = `❌ Error en el servidor: ${e.message}`;
      statusEl.style.color = '#ff9b85';
    });
  } catch (err) {
    statusEl.textContent = `❌ Error: JSON no válido (${err.message})`;
  }
}

function copyPayloadFormatter() {
  const code = document.getElementById("ttn-payload-code").innerText;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(code)
      .then(() => showToast('Código copiado. Pégalo en TTN: <strong>Payload formatters › Uplink</strong>', 'success', 'Código copiado'))
      .catch(() => showToast('No se pudo copiar automáticamente. Selecciona el código manualmente.', 'warning', 'Atención'));
  } else {
    showToast('Tu navegador no soporta copiar automáticamente. Selecciona el código con Ctrl+A.', 'info', 'Consejo');
  }
}

function exportCSV() {
  window.location.href = "/api/export/csv";
}

// -------------------------------------------------------------
// GESTIÓN DEL ENLACE MQTT CON THE THINGS NETWORK (TTN)
// -------------------------------------------------------------
function loadMqttStatus() {
  fetch("/api/mqtt/status")
    .then(r => r.json())
    .then(s => {
      const badge = document.getElementById("mqtt-badge");
      const msgCount = document.getElementById("mqtt-msg-count");
      const lastTime = document.getElementById("mqtt-last-time");
      const statusDetail = document.getElementById("mqtt-status-detail");
      const brokerInput = document.getElementById("mqtt-broker-input");
      const portInput = document.getElementById("mqtt-port-input");
      const appIdInput = document.getElementById("mqtt-appid-input");

      if (brokerInput && !brokerInput.dataset.modified) {
        if (s.broker) brokerInput.value = s.broker;
      }
      if (portInput && !portInput.dataset.modified) {
        if (s.port) portInput.value = s.port;
      }
      if (appIdInput && !appIdInput.dataset.modified) {
        if (s.app_id) appIdInput.value = s.app_id;
      }

      if (badge) {
        if (s.connected) {
          badge.className = "badge badge-success";
          badge.textContent = "🟢 Conectado";
        } else {
          badge.className = "badge badge-secondary";
          badge.textContent = "🔴 Desconectado";
        }
      }

      updateHeaderStatus(s.connected);

      if (msgCount) msgCount.textContent = s.messages_count || 0;
      if (lastTime) lastTime.textContent = s.last_message_time || "—";
      if (statusDetail) {
        let text = s.status_text || 'Esperando conexión…';
        if (s.last_error) text += ` | ⚠ ${s.last_error}`;
        statusDetail.textContent = text;
      }
    })
    .catch(err => console.debug("MQTT status poll error:", err));
}

function saveAndConnectMQTT() {
  const broker = document.getElementById("mqtt-broker-input").value.trim();
  const port   = parseInt(document.getElementById("mqtt-port-input").value.trim()) || 8883;
  const appId  = document.getElementById("mqtt-appid-input").value.trim();
  const apiKey = document.getElementById("mqtt-apikey-input").value.trim();
  const hint   = document.getElementById("apikey-hint");

  // Validación inline — sin alert()
  if (!apiKey) {
    if (hint) { hint.textContent = "⚠ Debes pegar la clave API de TTN antes de conectar."; hint.className = "form-hint error mt-4"; }
    document.getElementById("mqtt-apikey-input").focus();
    showToast('Pega tu clave API de TTN (empieza con NNSXS…) en el campo indicado.', 'warning', 'Falta la API Key');
    return;
  }
  if (hint) { hint.textContent = "Clave detectada. Conectando…"; hint.className = "form-hint success mt-4"; }

  const statusDetail = document.getElementById("mqtt-status-detail");
  const btnConnect   = document.getElementById("btn-mqtt-connect");

  if (statusDetail) statusDetail.textContent = "⏳ Guardando credenciales y conectando a TTN…";
  if (btnConnect)   { btnConnect.disabled = true; btnConnect.textContent = "⏳ Conectando…"; }

  const payload = {
    broker: broker || "nam1.cloud.thethings.network",
    port, app_id: appId || "cowlar-ganado-uets",
    api_key: apiKey, use_tls: port === 8883,
    enabled: true, connect_now: true
  };

  fetch("/api/mqtt/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  })
  .then(r => r.json())
  .then(() => {
    showToast('Credenciales guardadas. Cowlar está estableciendo el enlace seguro con TTN…', 'success', 'MQTT Conectando');
    if (hint) { hint.textContent = "Generar clave en TTN: Integrations › MQTT › Generate new API key"; hint.className = "form-hint mt-4"; }
    if (btnConnect) { btnConnect.disabled = false; btnConnect.innerHTML = '🚀 Conectar a TTN'; }
    loadMqttStatus();
  })
  .catch(e => {
    showToast(`Error al conectar MQTT: ${e.message}`, 'error', 'Error de conexión');
    if (statusDetail) statusDetail.textContent = `❌ Error: ${e.message}`;
    if (btnConnect)   { btnConnect.disabled = false; btnConnect.innerHTML = '🚀 Conectar a TTN'; }
    if (hint) { hint.className = "form-hint error mt-4"; hint.textContent = "Error al conectar. Verifica la clave y tu conexión a Internet."; }
  });
}

function disconnectMQTT() {
  const btn = document.getElementById("btn-mqtt-disconnect");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Deteniendo…"; }

  fetch("/api/mqtt/disconnect", { method: "POST" })
    .then(r => r.json())
    .then(() => {
      showToast('El enlace MQTT con TTN ha sido detenido.', 'info', 'MQTT Desconectado');
      loadMqttStatus();
    })
    .catch(e => {
      showToast(`Error al desconectar: ${e.message}`, 'error', 'Error');
    })
    .finally(() => {
      if (btn) { btn.disabled = false; btn.textContent = "⏹ Detener"; }
    });
}

function toggleApiKeyVisibility() {
  const input = document.getElementById("mqtt-apikey-input");
  if (input) {
    input.type = input.type === "password" ? "text" : "password";
  }
}
