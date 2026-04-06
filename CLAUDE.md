# Proyecto 17 — Memorizer

> Agente personal de memoria que organiza información diaria usando Telegram y Claude AI

## Contexto

Memorizer es un bot de Telegram que recibe mensajes diarios (links de LinkedIn, notas, ideas, contactos, videos de YouTube) y los clasifica automáticamente usando Claude API. Enriquece el contenido (extrae metadatos de YouTube con yt_dlp), valora relevancia, y redistribuye a grupos temáticos (Negocio, Tecnología, Creatividad, Miscelánea). Todo se almacena en SQLite con búsqueda full-text para consultas posteriores.

## Arquitectura

- **Entrada**: Grupo Telegram "Diario" recibe mensajes de cualquier tipo
- **Procesamiento**:
  - `python-telegram-bot` intercepta mensajes
  - `yt_dlp` extrae metadatos de YouTube
  - Claude API clasifica (tema, valor 1-10, tags, consejeros)
  - SQLite + FTS5 almacena con búsqueda full-text
- **Salida**: Reenvía a grupos temáticos con formato estructurado (valoración, tags, consejeros)
- **Ejecución**:
  - Menú tray macOS: `python memorizer_tray.py` (muestra estados 🧠, 🧠✨, 🧠💤, 🧠💀)
  - CLI: `python -m src.bot`
  - Docker: `docker compose up -d`

## Stack

- Python 3.13+
- python-telegram-bot, Anthropic SDK, yt_dlp, SQLite, rumps (menú tray)

## Notas para IAs

1. **Setup**: Requiere `.env` con `TELEGRAM_BOT_TOKEN`, `TELEGRAM_GROUP_ID`, IDs de grupos temáticos, `ANTHROPIC_API_KEY`
2. **Comandos del bot**: `/buscar <texto>`, `/resumen [días]`, `/stats`, `/help`
3. **Sonido opcional**: Busca `~/Library/Sounds/notification.wav` en macOS para reproducir al procesar
4. **Modelos**: Default es `claude-sonnet-4-6`, configurable en `.env`
5. **Estructura**: `src/bot.py` contiene lógica principal; usa flujo: recibir → clasificar → enriquecer → valorar → reenviar
6. **MacMini**: Ejecutar sin interfaz gráfica con `python -m src.bot`
