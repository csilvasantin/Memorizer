# Memorizer

Agente personal de memoria que organiza tu informacion diaria usando Telegram y Claude AI.

## Como funciona

1. **Recopila** - Envia mensajes a un grupo de Telegram (links de LinkedIn, notas de WhatsApp, ideas, contactos, videos de YouTube...)
2. **Clasifica** - El bot clasifica automaticamente cada mensaje usando Claude API (negocio, tecnologia, creatividad, etc.)
3. **Enriquece** - Si el mensaje contiene un video de YouTube, extrae titulo y descripcion con `yt_dlp` para una clasificacion precisa
4. **Valora** - Los videos y contenido multimedia reciben una valoracion del 1 al 10 segun relevancia para Admira Next
5. **Distribuye** - Reenvia el contenido al grupo tematico correspondiente (Negocio, Tecnologia, Creatividad, Miscelanea) con la valoracion y los consejeros asignados
6. **Almacena** - Todo se guarda en SQLite con busqueda full-text
7. **Consulta** - Pregunta al bot y Claude responde con contexto de tu historial

## Setup

### 1. Bot de Telegram

El bot ya esta creado: [@Memorizer2Bot](https://t.me/Memorizer2Bot)

### 2. Obtener Group ID

1. Agrega @Memorizer2Bot a tu grupo de Telegram
2. Envia un mensaje al grupo
3. Visita `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Busca el `chat.id` del grupo (numero negativo)

### 3. Configurar

```bash
cp .env.example .env
# Edita .env con tus tokens
```

Variables necesarias en `.env`:
- `TELEGRAM_BOT_TOKEN` - Token del bot de Telegram
- `TELEGRAM_GROUP_ID` - ID del grupo Diario (0 = cualquier grupo)
- `TELEGRAM_GROUP_NEGOCIO` - ID del grupo de Negocio
- `TELEGRAM_GROUP_TECNOLOGIA` - ID del grupo de Tecnologia
- `TELEGRAM_GROUP_CREATIVIDAD` - ID del grupo de Creatividad
- `TELEGRAM_GROUP_MISCELANEA` - ID del grupo de Miscelanea
- `ANTHROPIC_API_KEY` - API key de Anthropic
- `CLAUDE_MODEL` - Modelo a usar (default: claude-sonnet-4-6)

### 4. Ejecutar

**Con menu bar en macOS (recomendado para desarrollo):**
```bash
pip install -r requirements.txt
python memorizer_tray.py
```
Muestra un icono 🧠 en la barra de menu con opciones de reiniciar/detener/salir.
- 🧠 = corriendo
- 🧠✨ = procesando mensaje
- 🧠💤 = detenido
- 🧠💀 = el proceso murio

**Sin interfaz grafica (recomendado para servidores/MacMini):**
```bash
pip install -r requirements.txt
python -m src.bot
```

**Con Docker:**
```bash
docker compose up -d
```

## Notificacion sonora (macOS)

Si existe `~/Library/Sounds/notification.wav`, el bot reproduce ese sonido cada vez que procesa y reenvia un mensaje. Funciona solo en macOS y es no-bloqueante.

## Comandos del bot

| Comando | Descripcion |
|---------|-------------|
| `/buscar <texto>` | Buscar en tus memorias |
| `/resumen [dias]` | Resumen de los ultimos N dias (default: 7) |
| `/stats` | Estadisticas de memorias guardadas |
| `/help` | Mostrar ayuda |

## Arquitectura

```
Grupo Diario (Telegram)
    |
    v
Memorizer Bot (python-telegram-bot)
    |
    +--> yt_dlp: extrae metadatos de YouTube
    |
    +--> Claude API: clasifica, resume y valora
    |
    +--> SQLite: almacena con FTS5
    |
    +--> Grupos destino (Negocio/Tecnologia/Creatividad/Miscelanea)
         con valoracion + consejeros asignados
```

### Ejemplo de mensaje reenviado

```
📊 [NEGOCIO] — enviado por Carlos Silva

_Steve Jobs habla sobre liderazgo y la importancia de contratar talento_

https://www.youtube.com/shorts/47QQAMKF3zk

🎯 Valoracion: 8/10 ⭐⭐⭐⭐⭐⭐⭐⭐
_Leccion directa de liderazgo aplicable al equipo directivo._
🏷 #liderazgo · #management · #talento

👥 Consejo (Mesa completa): CEO, CFO, COO, CTO, CCO, CSO, CXO, CDO
```

## Tech Stack

- Python 3.13+
- python-telegram-bot
- Anthropic SDK (Claude API)
- yt_dlp (metadatos de YouTube)
- SQLite + FTS5
- rumps (menu bar macOS, opcional)
- Docker
