#!/bin/bash
# AuraPresenter - Auto-updater & Launcher para Mac

echo "◈ Iniciando AuraPresenter..."
echo "Verificando actualizaciones desde GitHub..."

# Asegurarnos de estar en la carpeta correcta
cd "$(dirname "$0")"

# Traer los últimos cambios de la rama main
git pull origin main

# Iniciar el backend en segundo plano
echo "Iniciando motor de Visión (Backend)..."
cd backend
source .venv/bin/activate
python server.py &
BACKEND_PID=$!

# Iniciar el frontend
echo "Iniciando Interfaz de Usuario (Frontend)..."
cd ../frontend
# Solo instalar dependencias si hubo cambios en package.json
pnpm install --silent
pnpm dev &
FRONTEND_PID=$!

echo "================================================="
echo "✅ AuraPresenter está corriendo en http://localhost:5173"
echo "Presiona Ctrl+C para apagar todo."
echo "================================================="

# Esperar a que el usuario presione Ctrl+C para matar los procesos
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM
wait
