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

## 🚀 Cómo usar AuraPresenter (Usuarios Finales)

¡AuraPresenter ahora es una **aplicación de escritorio nativa e independiente**! Ya no necesitas instalar Python ni Node.js para utilizarla.

1. Ve a la sección de **Releases** en GitHub.
2. Descarga la última versión para tu sistema operativo (ej. `AuraPresenter-mac.zip` o `AuraPresenter-windows.exe`).
3. Extrae el archivo y ejecuta la aplicación.
4. Se abrirá una ventana que activará tu cámara automáticamente.
5. Para usar tu celular como control remoto, asegúrate de estar en la misma red Wi-Fi y escanea el código QR que aparece en la pantalla.

> **Nota para usuarios de Mac:** Al abrir la aplicación por primera vez, macOS te pedirá permisos para usar la Cámara y para controlar el sistema (Accesibilidad) para poder cambiar las diapositivas.

---

## 🛠️ Desarrollo y Compilación (Para Desarrolladores)

Si deseas modificar el código o compilar la aplicación por ti mismo, AuraPresenter incluye un pipeline de empaquetado automatizado que une el frontend estático de Vite con el backend de Python usando `PyInstaller` y `PyWebView`.

### Requisitos Previos

- Python 3.11 o superior.
- Node.js y `pnpm` instalado (`npm i -g pnpm`).
- (Para empaquetar) Sistema Operativo objetivo (Mac, Windows, o Linux).

### Configuración del Entorno

```bash
# 1. Clonar el repositorio y entrar
git clone https://github.com/jbam303/AuraPresenter.git
cd AuraPresenter

# 2. Configurar el backend
cd backend
python -m venv .venv
source .venv/bin/activate  # O .venv\Scripts\activate en Windows
pip install -r requirements.txt
```

> [!WARNING]
> **Modelos de MediaPipe:** Debes descargar los modelos pre-entrenados de Google (terminación `.task`) y colocarlos directamente dentro de la carpeta `/backend/`.
> - [hand_landmarker.task](https://developers.google.com/mediapipe/solutions/vision/hand_landmarker)
> - [pose_landmarker.task](https://developers.google.com/mediapipe/solutions/vision/pose_landmarker)

### Empaquetado Automático (Build)

En lugar de correr el servidor y el frontend por separado, hemos integrado todo en un script de compilación único.

Desde la raíz del proyecto, ejecuta:

```bash
python backend/build.py
```

Este script hará lo siguiente:
1. Compilará el frontend estático con `pnpm run build`.
2. Empaquetará el servidor Python, los modelos de visión y el HTML/JS resultante en un solo ejecutable usando `PyInstaller`.
3. (En macOS) Limpiará los atributos extendidos problemáticos (`com.apple.FinderInfo`) y firmará el código localmente de forma automática.

El binario final (ej. `AuraPresenter.app` en Mac o `AuraPresenter.exe` en Windows) quedará guardado en la carpeta `releases/`.

---

## 📱 Cómo usar el Control Remoto (Celular) en Desarrollo

Por razones de privacidad, los navegadores bloquean el acceso al acelerómetro (`DeviceMotion`) en redes locales sin HTTPS. Si modificas el código y pruebas el celular en la misma red local:

1. En tu teléfono Android, abre Google Chrome.
2. Escribe en la barra de direcciones: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
3. En la caja de texto, escribe la IP local exacta que te indica la consola (Ej: `http://192.168.1.5:5173`).
4. Cambia el estado a **Enabled** y reinicia Chrome.
5. Escanea el código QR que aparece en la pantalla de la aplicación.

En la aplicación de tu celular, podrás utilizar el **Slider de Sensibilidad** para configurar cuánta fuerza requiere el latigazo para pasar de diapositiva.

---

## 🕹️ Guía de Gestos y Controles

### Control por Cámara (Hand Tracking)
Levanta tu mano hacia la cámara y realiza movimientos firmes de lado a lado.
- **Deslizar hacia la Derecha (Swipe Right):** Pasa a la siguiente diapositiva *(Simula la tecla Flecha Derecha)*.
- **Deslizar hacia la Izquierda (Swipe Left):** Vuelve a la diapositiva anterior *(Simula la tecla Flecha Izquierda)*.

### Control por Acelerómetro (Celular)
Sostén tu celular en la mano.
- **Flick a la Derecha (Giro rápido de muñeca):** Pasa a la siguiente diapositiva.
- **Flick a la Izquierda:** Vuelve a la diapositiva anterior.

Ambos controles pueden usarse simultáneamente sin interferir el uno con el otro. Cada gesto exitoso iluminará la pantalla del escritorio y dejará un registro en el panel lateral con la procedencia del evento (📱 o 📷).
