/**
 * AuraPresenter — Phone Remote Client
 *
 * Reads the device accelerometer via DeviceMotion API
 * and streams telemetry to the backend over WebSocket.
 */

import "./phone.css";

// =============================================================================
// Configuration
// =============================================================================

const WS_PORT = window.location.protocol === 'https:' ? 8766 : 8765;
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:${WS_PORT}`;
const RECONNECT_DELAY_MS = 2000;
const SEND_INTERVAL_MS = 33; // ~30 Hz
const MAX_LOG_ENTRIES = 15;

// =============================================================================
// DOM Elements
// =============================================================================

const connectionIndicator = document.getElementById("phone-connection");
const connectionText = document.getElementById("phone-connection-text");
const stateIcon = document.getElementById("state-icon");
const stateTitle = document.getElementById("state-title");
const stateSubtitle = document.getElementById("state-subtitle");
const readyState = document.getElementById("phone-ready-state");
const axBar = document.getElementById("axis-x-bar");
const ayBar = document.getElementById("axis-y-bar");
const azBar = document.getElementById("axis-z-bar");
const axVal = document.getElementById("axis-x-val");
const ayVal = document.getElementById("axis-y-val");
const azVal = document.getElementById("axis-z-val");
const gestureFlash = document.getElementById("phone-gesture-flash");
const flashIcon = document.getElementById("phone-flash-icon");
const flashLabel = document.getElementById("phone-flash-label");
const gestureLog = document.getElementById("phone-gesture-log");

// Sensitivity Settings
const sensSlider = document.getElementById("sensitivity-slider");
const sensVal = document.getElementById("sensitivity-val");

// =============================================================================
// State
// =============================================================================

/** @type {WebSocket | null} */
let ws = null;
let reconnectTimer = null;
let sendTimer = null;
let pingTimer = null;
let latestAccel = { x: 0, y: 0, z: 0 };
let sensorActive = false;

// =============================================================================
// Sensor Visualization
// =============================================================================

/**
 * Update the sensor bar visualization for a single axis.
 * Value range: roughly -20 to +20 m/s², centered at 0.
 */
function updateAxisBar(bar, valEl, value) {
  const maxVal = 20;
  const clamped = Math.max(-maxVal, Math.min(maxVal, value));
  const pct = (clamped / maxVal) * 50; // percentage of half-track

  if (pct >= 0) {
    bar.style.left = "50%";
    bar.style.width = `${pct}%`;
  } else {
    bar.style.left = `${50 + pct}%`;
    bar.style.width = `${-pct}%`;
  }

  valEl.textContent = value.toFixed(1);
}

function updateSensorUI() {
  updateAxisBar(axBar, axVal, latestAccel.x);
  updateAxisBar(ayBar, ayVal, latestAccel.y);
  updateAxisBar(azBar, azVal, latestAccel.z);
}

// =============================================================================
// DeviceMotion
// =============================================================================

function startSensor() {
  if (sensorActive) return;

  window.addEventListener("devicemotion", onDeviceMotion);
  sensorActive = true;

  // Start throttled send loop
  sendTimer = setInterval(sendTelemetry, SEND_INTERVAL_MS);
}

function onDeviceMotion(event) {
  // Prefer acceleration (without gravity) for cleaner signal
  const accel = event.acceleration || event.accelerationIncludingGravity;
  if (accel) {
    latestAccel.x = accel.x || 0;
    latestAccel.y = accel.y || 0;
    latestAccel.z = accel.z || 0;
  }
  updateSensorUI();
}

function sendTelemetry() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "telemetry",
      ax: Math.round(latestAccel.x * 100) / 100,
      ay: Math.round(latestAccel.y * 100) / 100,
      az: Math.round(latestAccel.z * 100) / 100,
    }));
  }
}

// =============================================================================
// Sensitivity
// =============================================================================

sensSlider.addEventListener("input", (e) => {
  const val = parseFloat(e.target.value).toFixed(1);
  sensVal.textContent = val;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "update_sensitivity",
      threshold: parseFloat(val)
    }));
  }
});

// =============================================================================
// Gesture Feedback
// =============================================================================

function triggerGestureFlash(gesture) {
  const config = {
    FLICK_RIGHT: { icon: "→", label: "Next Slide" },
    FLICK_LEFT: { icon: "←", label: "Previous Slide" },
  };

  const c = config[gesture] || { icon: "?", label: gesture };
  flashIcon.textContent = c.icon;
  flashLabel.textContent = c.label;

  gestureFlash.classList.remove("hidden");
  gestureFlash.classList.add("active");

  // Vibrate for haptic feedback (Android)
  if (navigator.vibrate) {
    navigator.vibrate(100);
  }

  setTimeout(() => {
    gestureFlash.classList.remove("active");
    gestureFlash.classList.add("hidden");
  }, 700);
}

function addLogEntry(gesture) {
  const empty = gestureLog.querySelector(".phone-log-empty");
  if (empty) empty.remove();

  const li = document.createElement("li");
  li.className = "phone-log-entry";

  const name = document.createElement("span");
  name.className = "phone-log-name";
  name.textContent = gesture.replace("_", " ");

  const time = document.createElement("span");
  time.className = "phone-log-time";
  time.textContent = new Date().toLocaleTimeString();

  li.appendChild(name);
  li.appendChild(time);
  gestureLog.insertBefore(li, gestureLog.firstChild);

  while (gestureLog.children.length > MAX_LOG_ENTRIES) {
    gestureLog.removeChild(gestureLog.lastChild);
  }
}

// =============================================================================
// Connection State UI
// =============================================================================

function setConnected(connected) {
  connectionIndicator.className = `phone-indicator ${connected ? "connected" : "disconnected"}`;
  connectionText.textContent = connected ? "Connected" : "Disconnected";

  if (connected) {
    readyState.className = "state-ready";
    stateIcon.textContent = "🎯";
    stateTitle.textContent = "Ready!";
    stateSubtitle.textContent = "Flick your phone left or right";
  } else {
    readyState.className = "state-waiting";
    stateIcon.textContent = "📱";
    stateTitle.textContent = "Connecting...";
    stateSubtitle.textContent = "Make sure the backend server is running";
  }
}

// =============================================================================
// WebSocket Connection
// =============================================================================

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    console.log("[PhoneRemote] Connected");
    // Identify as phone client and send initial sensitivity
    ws.send(JSON.stringify({ type: "phone_init" }));
    ws.send(JSON.stringify({ 
      type: "update_sensitivity", 
      threshold: parseFloat(sensSlider.value) 
    }));
    
    setConnected(true);
    startSensor();

    // Start Ping loop
    pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 5000);
  });

  ws.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === "phone_gesture") {
        triggerGestureFlash(data.gesture);
        addLogEntry(data.gesture);
      }
    } catch (err) {
      // Ignore non-JSON messages
    }
  });

  ws.addEventListener("close", () => {
    console.log("[PhoneRemote] Disconnected");
    setConnected(false);
    if (pingTimer) clearInterval(pingTimer);
    scheduleReconnect();
  });

  ws.addEventListener("error", () => {
    ws.close();
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_DELAY_MS);
}

// =============================================================================
// Bootstrap
// =============================================================================

setConnected(false);
connect();
