import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID
from src.classifier import classify_message
from src.storage import MemoryStorage
from src.query import answer_query, generate_summary, get_stats_text
from src.council import (
    get_recipients,
    format_council_notification,
    get_destination_group,
    format_forwarded_message,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

storage = MemoryStorage()


def _get_content_type(message) -> tuple[str, str]:
    """Extract content and type from a Telegram message."""
    if message.text:
        return message.text, "text"
    if message.caption:
        content = message.caption
        if message.photo:
            return content, "photo"
        if message.video:
            return content, "video"
        if message.document:
            return content, "document"
        return content, "text"
    if message.photo:
        return "[Foto sin caption]", "photo"
    if message.video:
        return "[Video sin caption]", "video"
    if message.document:
        return f"[Documento: {message.document.file_name or 'sin nombre'}]", "document"
    if message.voice:
        return "[Mensaje de voz]", "voice"
    if message.audio:
        return "[Audio]", "audio"
    if message.sticker:
        return "[Sticker]", "sticker"
    return "[Contenido no soportado]", "unknown"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process every message in the group."""
    message = update.effective_message
    if not message:
        return

    # Only process messages from the configured group (0 = any group)
    if TELEGRAM_GROUP_ID and update.effective_chat.id != TELEGRAM_GROUP_ID:
        return

    content, content_type = _get_content_type(message)
    author = message.from_user.full_name if message.from_user else "unknown"

    # Skip bot commands
    if content.startswith("/"):
        return

    logger.info(f"Processing message from {author}: {content[:80]}...")

    # Classify with Claude
    classification = classify_message(content)
    result = await classification

    # Store in database
    await storage.save_memory(
        telegram_message_id=message.message_id,
        chat_id=update.effective_chat.id,
        author=author,
        content=content,
        content_type=content_type,
        source=result["source"],
        category=result["category"],
        summary=result.get("summary"),
        entities=result.get("entities"),
        urls=result.get("urls"),
    )

    # React with emoji based on category
    category_emoji = {
        "trabajo": "💼",
        "personal": "👤",
        "referencia": "📌",
        "idea": "💡",
        "contacto": "📇",
        "evento": "📅",
        "otro": "📝",
        "tecnología": "🔧",
        "creatividad": "🎨",
        "negocio": "📊",
    }
    emoji = category_emoji.get(result["category"], "📝")
    try:
        await message.set_reaction(emoji)
    except Exception:
        pass  # Reactions may not be supported

    # Forward to destination group
    category = result["category"]
    recipients = get_recipients(category)
    destination_group = get_destination_group(category)

    if destination_group:
        forwarded = format_forwarded_message(
            category=category,
            content=content,
            summary=result.get("summary", ""),
            recipients=recipients,
            author=author,
        )
        try:
            await context.bot.send_message(
                chat_id=destination_group,
                text=forwarded,
                parse_mode="Markdown",
            )
            logger.info(f"Forwarded to group {destination_group} (category: {category})")
        except Exception as e:
            logger.warning(f"Could not forward to destination group {destination_group}: {e}")


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buscar <query> command."""
    if not context.args:
        await update.message.reply_text("Uso: /buscar <texto a buscar>")
        return

    query = " ".join(context.args)
    await update.message.reply_text("Buscando...")
    response = await answer_query(query)
    await update.message.reply_text(response)


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resumen [dias] command."""
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass

    await update.message.reply_text(f"Generando resumen de {days} días...")
    response = await generate_summary(days)
    await update.message.reply_text(response)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    response = await get_stats_text()
    await update.message.reply_text(response)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    text = (
        "Memorizer - Tu asistente de memoria personal\n\n"
        "Envía cualquier mensaje al grupo y lo clasifico automáticamente.\n\n"
        "Comandos:\n"
        "/buscar <texto> - Buscar en tus memorias\n"
        "/resumen [dias] - Resumen de los últimos N días (default: 7)\n"
        "/stats - Estadísticas de memorias guardadas\n"
        "/help - Mostrar esta ayuda"
    )
    await update.message.reply_text(text)


async def post_init(application: Application):
    """Initialize database on startup."""
    await storage.init_db()
    logger.info("Database initialized")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set. Check your .env file.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    # Capture all non-command messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Memorizer bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
