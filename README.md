# Memorizer

Agente personal de memoria que organiza tu informacion diaria usando Telegram y Claude AI.

## Como funciona

1. **Recopila** - Envia mensajes a un grupo de Telegram (links de LinkedIn, notas de WhatsApp, ideas, contactos...)
2. **Clasifica** - El bot clasifica automaticamente cada mensaje usando Claude API (trabajo, personal, referencia, idea, contacto, evento)
3. **Almacena** - Todo se guarda en SQLite con busqueda full-text
4. **Consulta** - Pregunta al bot y Claude responde con contexto de tu historial

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

### 4. Ejecutar

**Con Docker (recomendado):**
```bash
docker compose up -d
```

**Sin Docker:**
```bash
pip install -r requirements.txt
python -m src.bot
```

## Comandos del bot

| Comando | Descripcion |
|---------|-------------|
| `/buscar <texto>` | Buscar en tus memorias |
| `/resumen [dias]` | Resumen de los ultimos N dias (default: 7) |
| `/stats` | Estadisticas de memorias guardadas |
| `/help` | Mostrar ayuda |

## Arquitectura

```
Telegram Group --> Bot (python-telegram-bot) --> Classifier (Claude API) --> SQLite
                                                                              |
                              Claude API <-- Query Engine <-- /buscar command
```

## Tech Stack

- Python 3.12
- python-telegram-bot
- Anthropic SDK (Claude API)
- SQLite + FTS5
- Docker
