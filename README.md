# AuraPresenter ◈

Un controlador de presentaciones de alto rendimiento y baja latencia que te permite avanzar o retroceder diapositivas (PowerPoint, Keynote, Google Slides) utilizando gestos físicos. 

El sistema soporta dos modalidades de control simultáneas:
1. **Visión Computacional (Cámara):** Seguimiento de manos en tiempo real para detectar deslizamientos (swipes) en el aire.
2. **Telemetría Móvil (Celular):** Un control remoto web que utiliza el acelerómetro del celular para detectar movimientos rápidos (flicks) de muñeca.

---

## 🏛️ Arquitectura del Proyecto

El proyecto está diseñado con una arquitectura desacoplada y asíncrona para garantizar que el pesado procesamiento de imágenes no congele la interfaz gráfica, logrando 30+ FPS estables en el renderizado del esqueleto.

### 1. Backend (Python)
El cerebro del sistema. Se encarga de procesar las imágenes y coordinar los clientes.
- **MediaPipe Tasks API:** Se utiliza el nuevo motor de Machine Learning de Google para una inferencia ultra rápida del esqueleto de la mano (`hand_landmarker`) y del cuerpo (`pose_landmarker`).
- **Orquestador WebSocket:** Un servidor asíncrono (`websockets.asyncio`) de canal dual. Administra "Viewers" (pantallas de escritorio que renderizan el esqueleto) y "Phones" (celulares que envían datos de acelerómetro).
- **Control de Sistema (macOS):** En lugar de usar librerías pesadas y propensas a errores de compilación como `PyAutoGUI`, el servidor ejecuta scripts nativos de `AppleScript` (`osascript`) para simular las pulsaciones de las teclas de dirección a nivel del sistema operativo.
- **Máquinas de Estado Finito (FSM):** Tanto `gesture_engine.py` (cámara) como `motion_engine.py` (celular) implementan FSM para evitar pulsaciones duplicadas, aplicando un *cooldown* y calculando la velocidad direccional.

### 2. Frontend (Vite + Vanilla JS + CSS Puro)
Una interfaz de usuario fluida y visualmente impactante.
- **Desktop UI (`index.html`):** Un panel de control de aspecto premium (*Glassmorphism*). Abre una conexión WebSocket con el backend para recibir las coordenadas normalizadas del cuerpo y las manos, dibujando un esqueleto de líneas brillantes en un elemento `<canvas>`. Muestra estadísticas de FPS, logs de gestos y un código QR generado dinámicamente.
- **Phone Remote (`phone.html`):** Una aplicación web móvil servida directamente desde el servidor local. Lee la API `DeviceMotion` nativa del navegador a ~30Hz, detecta los cambios de inercia y envía la telemetría al backend mediante WebSockets. Cuenta con retroalimentación háptica (vibración) nativa.

---

## 🚀 Requisitos Previos

- **Para el Backend:** Python 3.11 o superior.
- **Para el Frontend:** Node.js y `pnpm` instalado (`npm i -g pnpm`).
- **Sistema Operativo:** El backend actualmente utiliza comandos específicos de macOS (`osascript`) para el control del teclado.

---

## ⚙️ Instalación y Puesta en Marcha

### 1. Configuración del Backend (Cámara y Servidor)

```bash
# 1. Entrar a la carpeta del backend
cd backend

# 2. Crear y activar el entorno virtual
python -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

> [!WARNING]
> **Modelos de MediaPipe:** Debes descargar los modelos pre-entrenados de Google (terminación `.task`) y colocarlos directamente dentro de la carpeta `/backend/`.
> - [hand_landmarker.task](https://developers.google.com/mediapipe/solutions/vision/hand_landmarker)
> - [pose_landmarker.task](https://developers.google.com/mediapipe/solutions/vision/pose_landmarker)

```bash
# 4. Iniciar el servidor (escuchará en la IP local, puerto 8765)
python server.py
```

### 2. Configuración del Frontend (Panel de Control y Remote)

Abre una **nueva terminal** y ejecuta:

```bash
# 1. Entrar a la carpeta del frontend
cd frontend

# 2. Instalar dependencias con pnpm
pnpm install

# 3. Iniciar el servidor de desarrollo en la red local
pnpm dev
```
Haz clic en el enlace local (ej. `http://localhost:5173`) para abrir el panel de control. 

---

## 📱 Cómo usar el Control Remoto (Celular)

Por razones de privacidad, los navegadores modernos (como Google Chrome en Android) bloquean el acceso al acelerómetro (`DeviceMotion`) si la página no tiene un certificado SSL válido (HTTPS). Como este proyecto se ejecuta en una red local (`192.168.x.x`), Chrome lo considerará inseguro. 

Para habilitar los sensores para desarrollo local en **1 minuto**:

1. En tu teléfono Android, abre Google Chrome.
2. Escribe en la barra de direcciones: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
3. En la caja de texto, escribe la IP local exacta que te indica Vite en la consola (Ej: `http://192.168.1.5:5173`).
4. Cambia el estado a **Enabled**.
5. Toca el botón azul **Relaunch** en la parte inferior para reiniciar el navegador.
6. Escanea el código QR que aparece en la pantalla del Panel de Control de tu computadora.

*¡Listo! Verás las barras del acelerómetro moverse en tiempo real.*

---

## 🕹️ Guía de Gestos y Controles

### Control por Cámara (Hand Tracking)
Levanta tu mano hacia la cámara y realiza movimientos firmes de lado a lado.
- **Deslizar hacia la Derecha (Swipe Right):** Pasa a la siguiente diapositiva *(Simula la tecla Flecha Derecha)*.
- **Deslizar hacia la Izquierda (Swipe Left):** Vuelve a la diapositiva anterior *(Simula la tecla Flecha Izquierda)*.

### Control por Acelerómetro (Celular)
Sostén tu celular en la mano.
- **Flick a la Derecha (Giro rápido de muñeca):** Pasa a la siguiente diapositiva *(Umbral: > 8.0 m/s²)*.
- **Flick a la Izquierda:** Vuelve a la diapositiva anterior.

Ambos controles pueden usarse simultáneamente sin interferir el uno con el otro. Cada gesto exitoso iluminará la pantalla del escritorio y dejará un registro en el panel lateral con la procedencia del evento (📱 o 📷).
