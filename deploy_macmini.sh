#!/bin/bash
# Deploy Memorizer to MacMini via SSH
# Usage: ./deploy_macmini.sh

set -e

HOST="macmini"
REMOTE_DIR="~/Memorizer"
ENV_FILE=".env"

echo "=== Conectando al MacMini ==="
ssh -o ConnectTimeout=10 "$HOST" "echo 'Conectado a MacMini OK'"

echo ""
echo "=== Clonando/actualizando repo ==="
ssh "$HOST" "
  if [ -d $REMOTE_DIR ]; then
    cd $REMOTE_DIR && git pull
  else
    git clone https://github.com/csilvasantin/Memorizer.git $REMOTE_DIR
  fi
"

echo ""
echo "=== Copiando .env ==="
scp "$ENV_FILE" "$HOST:$REMOTE_DIR/.env"

echo ""
echo "=== Instalando dependencias ==="
ssh "$HOST" "cd $REMOTE_DIR && pip3 install -r requirements.txt"

echo ""
echo "=== Creando directorio de datos ==="
ssh "$HOST" "mkdir -p $REMOTE_DIR/data"

echo ""
echo "=== Deteniendo instancia anterior (si existe) ==="
ssh "$HOST" "pkill -f 'src.bot' 2>/dev/null || true"
sleep 2

echo ""
echo "=== Arrancando Memorizer ==="
ssh "$HOST" "cd $REMOTE_DIR && nohup python3 -m src.bot > data/bot.log 2>&1 &"
sleep 3

echo ""
echo "=== Verificando ==="
ssh "$HOST" "ps aux | grep 'src.bot' | grep -v grep && echo 'Memorizer corriendo OK' || echo 'ERROR: no arrancó'"

echo ""
echo "=== Hecho ==="
