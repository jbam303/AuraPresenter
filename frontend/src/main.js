/**
 * AuraPresenter — Frontend Client
 *
 * Connects to the Python backend via WebSocket and renders
 * hand/body skeleton landmarks on a Canvas in real-time.
 */

import "./style.css";
import QRCode from "qrcode";

// =============================================================================
// Configuration
// =============================================================================

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8765`;
const RECONNECT_DELAY_MS = 2000;
const MAX_LOG_ENTRIES = 20;

// MediaPipe hand landmark connections (pairs of indices)
const HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],       // Thumb
  [0, 5], [5, 6], [6, 7], [7, 8],       // Index
  [0, 9], [9, 10], [10, 11], [11, 12],  // Middle
  [0, 13], [13, 14], [14, 15], [15, 16],// Ring
  [0, 17], [17, 18], [18, 19], [19, 20],// Pinky
  [5, 9], [9, 13], [13, 17],            // Palm
];

// MediaPipe pose landmark connections (simplified upper body)
const POSE_CONNECTIONS = [
  // Torso
  [11, 12], [11, 23], [12, 24], [23, 24],
  // Arms
  [11, 13], [13, 15], [12, 14], [14, 16],
  // Hands (wrist to index finger tip approximation)
  [15, 17], [15, 19], [15, 21],
  [16, 18], [16, 20], [16, 22],
  // Face outline
  [0, 1], [1, 2], [2, 3], [3, 7],
  [0, 4], [4, 5], [5, 6], [6, 8],
  // Shoulders to ears
  [9, 10], [11, 12],
];


// =============================================================================
// DOM Elements
// =============================================================================

const canvas = document.getElementById("skeleton-canvas");
const ctx = canvas.getContext("2d");
const connectionIndicator = document.getElementById("connection-indicator");
const connectionText = document.getElementById("connection-text");
const fpsValue = document.getElementById("fps-value");
const noCameraOverlay = document.getElementById("no-camera-overlay");
const canvasWrapper = document.getElementById("canvas-wrapper");
const gestureLog = document.getElementById("gesture-log");
const handCount = document.getElementById("hand-count");
const poseDetected = document.getElementById("pose-detected");
const handStatus = document.getElementById("hand-status");
const poseStatus = document.getElementById("pose-status");
const gestureFlash = document.getElementById("gesture-flash");
const gestureFlashIcon = document.getElementById("gesture-flash-icon");
const qrCanvas = document.getElementById("qr-canvas");
const phoneUrl = document.getElementById("phone-url");
const phoneRemoteStatus = document.getElementById("phone-remote-status");
const phoneRemoteLabel = document.getElementById("phone-remote-label");


// =============================================================================
// State
// =============================================================================

/** @type {WebSocket | null} */
let ws = null;
let frameCount = 0;
let lastFpsUpdate = performance.now();
let isConnected = false;
let reconnectTimer = null;


// =============================================================================
// Canvas Setup
// =============================================================================

function resizeCanvas() {
  const rect = canvasWrapper.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();


// =============================================================================
// Rendering
// =============================================================================

/**
 * Clear the canvas with a subtle fade trail effect.
 */
function clearCanvas() {
  const rect = canvasWrapper.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
}

/**
 * Draw a single joint point.
 */
function drawJoint(x, y, color, radius = 4) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();

  // Glow effect
  ctx.beginPath();
  ctx.arc(x, y, radius + 3, 0, Math.PI * 2);
  ctx.fillStyle = color.replace(")", ", 0.2)").replace("hsl", "hsla");
  ctx.fill();
}

/**
 * Draw a bone (connection between two joints).
 */
function drawBone(x1, y1, x2, y2, color, width = 2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.stroke();
}

/**
 * Render hand landmarks on the canvas.
 */
function renderHands(hands, canvasW, canvasH) {
  const jointColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--skeleton-hand-joint").trim();
  const boneColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--skeleton-hand-bone").trim();

  for (const hand of hands) {
    // Draw bones first (under joints)
    for (const [i, j] of HAND_CONNECTIONS) {
      if (hand[i] && hand[j]) {
        drawBone(
          hand[i].x * canvasW, hand[i].y * canvasH,
          hand[j].x * canvasW, hand[j].y * canvasH,
          boneColor, 2
        );
      }
    }

    // Draw joints
    for (let i = 0; i < hand.length; i++) {
      const lm = hand[i];
      // Fingertips (4, 8, 12, 16, 20) get larger dots
      const isTip = [4, 8, 12, 16, 20].includes(i);
      drawJoint(lm.x * canvasW, lm.y * canvasH, jointColor, isTip ? 6 : 3);
    }
  }
}

/**
 * Render pose (body) landmarks on the canvas.
 */
function renderPose(pose, canvasW, canvasH) {
  if (!pose) return;

  const jointColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--skeleton-joint").trim();
  const boneColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--skeleton-bone").trim();

  // Draw bones
  for (const [i, j] of POSE_CONNECTIONS) {
    if (
      pose[i] && pose[j] &&
      pose[i].visibility > 0.5 && pose[j].visibility > 0.5
    ) {
      drawBone(
        pose[i].x * canvasW, pose[i].y * canvasH,
        pose[j].x * canvasW, pose[j].y * canvasH,
        boneColor, 3
      );
    }
  }

  // Draw joints (only upper body: indices 0-24)
  for (let i = 0; i <= 24 && i < pose.length; i++) {
    const lm = pose[i];
    if (lm.visibility > 0.5) {
      drawJoint(lm.x * canvasW, lm.y * canvasH, jointColor, 5);
    }
  }
}

/**
 * Process and render a single frame from the backend.
 */
function renderFrame(data) {
  const rect = canvasWrapper.getBoundingClientRect();
  const canvasW = rect.width;
  const canvasH = rect.height;

  clearCanvas();

  // Render body first (behind hands)
  if (data.pose) {
    renderPose(data.pose, canvasW, canvasH);
  }

  // Render hands on top
  if (data.hands && data.hands.length > 0) {
    renderHands(data.hands, canvasW, canvasH);
  }

  // Update detection status
  updateDetectionStatus(data);

  // Update FPS counter
  frameCount++;
  const now = performance.now();
  if (now - lastFpsUpdate >= 1000) {
    fpsValue.textContent = frameCount;
    frameCount = 0;
    lastFpsUpdate = now;
  }

  // Handle gesture flash
  if (data.gesture) {
    triggerGestureFlash(data.gesture);
    addGestureLogEntry(data.gesture);
  }
}


// =============================================================================
// UI Updates
// =============================================================================

function updateDetectionStatus(data) {
  const numHands = data.hands ? data.hands.length : 0;
  const hasPose = !!data.pose;

  handCount.textContent = numHands > 0 ? numHands : "—";
  poseDetected.textContent = hasPose ? "Yes" : "—";

  handStatus.classList.toggle("active", numHands > 0);
  poseStatus.classList.toggle("active", hasPose);
}

function triggerGestureFlash(gesture) {
  const icons = {
    SWIPE_RIGHT: "→",
    SWIPE_LEFT: "←",
    FLICK_RIGHT: "→",
    FLICK_LEFT: "←",
  };

  // Re-query the icon from the DOM because replaceChild destroys the previous node
  const currentIcon = document.getElementById("gesture-flash-icon");
  if (!currentIcon) return;

  currentIcon.textContent = icons[gesture] || "?";
  gestureFlash.classList.remove("hidden");
  gestureFlash.classList.add("active");

  // Clone and replace to restart CSS animation
  const clone = currentIcon.cloneNode(true);
  currentIcon.parentNode.replaceChild(clone, currentIcon);

  setTimeout(() => {
    gestureFlash.classList.remove("active");
    gestureFlash.classList.add("hidden");
  }, 700);
}

function addGestureLogEntry(gesture, source = "camera") {
  // Remove the "empty" placeholder if present
  const emptyEntry = gestureLog.querySelector(".log-empty");
  if (emptyEntry) emptyEntry.remove();

  const li = document.createElement("li");
  li.className = "log-entry";

  const nameWrapper = document.createElement("span");

  const name = document.createElement("span");
  name.className = "log-gesture-name";
  name.textContent = gesture.replace("_", " ");
  nameWrapper.appendChild(name);

  // Source badge
  const badge = document.createElement("span");
  badge.className = `log-source source-${source}`;
  badge.textContent = source === "phone" ? "📱" : "📷";
  nameWrapper.appendChild(badge);

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = new Date().toLocaleTimeString();

  li.appendChild(nameWrapper);
  li.appendChild(time);

  // Insert at top
  gestureLog.insertBefore(li, gestureLog.firstChild);

  // Trim old entries
  while (gestureLog.children.length > MAX_LOG_ENTRIES) {
    gestureLog.removeChild(gestureLog.lastChild);
  }
}

function setConnectionState(connected) {
  isConnected = connected;
  connectionIndicator.className = `indicator ${connected ? "connected" : "disconnected"}`;
  connectionText.textContent = connected ? "Connected" : "Disconnected";

  if (connected) {
    noCameraOverlay.classList.add("hidden");
    canvasWrapper.classList.add("tracking");
  } else {
    noCameraOverlay.classList.remove("hidden");
    canvasWrapper.classList.remove("tracking");
    handCount.textContent = "—";
    poseDetected.textContent = "—";
    handStatus.classList.remove("active");
    poseStatus.classList.remove("active");
    fpsValue.textContent = "0";
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
    console.log("[AuraPresenter] Connected to backend");
    setConnectionState(true);
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  });

  ws.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === "frame") {
        renderFrame(data);
      } else if (data.type === "config") {
        handleServerConfig(data);
      } else if (data.type === "phone_gesture") {
        triggerGestureFlash(data.gesture);
        addGestureLogEntry(data.gesture, "phone");
      }
    } catch (err) {
      console.error("[AuraPresenter] Failed to parse message:", err);
    }
  });

  ws.addEventListener("close", () => {
    console.log("[AuraPresenter] Disconnected. Reconnecting...");
    setConnectionState(false);
    scheduleReconnect();
  });

  ws.addEventListener("error", (err) => {
    console.error("[AuraPresenter] WebSocket error:", err);
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
// Phone Remote / QR Code
// =============================================================================

function handleServerConfig(config) {
  const { local_ip, vite_port } = config;
  const url = `http://${local_ip}:${vite_port}/phone.html`;

  phoneUrl.textContent = url;

  // Generate QR code on the canvas
  QRCode.toCanvas(qrCanvas, url, {
    width: 140,
    margin: 1,
    color: {
      dark: "#1a1a2e",
      light: "#ffffff",
    },
  }).catch((err) => {
    console.error("[AuraPresenter] QR generation failed:", err);
  });
}


// =============================================================================
// Bootstrap
// =============================================================================

setConnectionState(false);
connect();
