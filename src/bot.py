import logging
import os
import subprocess
import sys
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReactionTypeEmoji
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

NOTIFICATION_SOUND = os.path.expanduser("~/Library/Sounds/notification.wav")


def _play_notification():
    """Play notification sound on macOS (non-blocking)."""
    if sys.platform == "darwin" and os.path.exists(NOTIFICATION_SOUND):
        subprocess.Popen(
            ["afplay", NOTIFICATION_SOUND],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


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
        await message.set_reaction([ReactionTypeEmoji(emoji=emoji)])
    except Exception as e:
        logger.warning(f"Could not set reaction: {e}")

    # Forward to destination group
    category = result["category"]
    recipients = get_recipients(category)
    destination_group = get_destination_group(category)

    if destination_group:
        review = result.get("review")
        rating = review.get("rating", 0) if review else 0
        forwarded = format_forwarded_message(
            category=category,
            content=content,
            summary=result.get("summary", ""),
            recipients=recipients,
            author=author,
            review=review,
        )

        # Add Boost button if there's a rating
        keyboard = None
        if rating:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🚀 Boost ({rating}/10)", callback_data="boost")]
            ])

        try:
            sent = await context.bot.send_message(
                chat_id=destination_group,
                text=forwarded,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            logger.info(f"Forwarded to group {destination_group} (category: {category})")
            _play_notification()

            # Save boost record for callback tracking
            if rating:
                memory_id = await storage.save_memory_get_id(
                    telegram_message_id=message.message_id,
                    chat_id=update.effective_chat.id,
                )
                if memory_id:
                    await storage.save_boost(
                        memory_id=memory_id,
                        forwarded_chat_id=destination_group,
                        forwarded_message_id=sent.message_id,
                        rating=int(rating) if isinstance(rating, (int, float)) else 0,
                    )

            # Write preview to file for CLI monitoring
            preview_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "last_preview.txt")
            with open(preview_path, "w") as f:
                f.write(forwarded + "\n")
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


async def handle_boost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Boost button press."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    message_id = query.message.message_id

    result = await storage.apply_boost(chat_id, message_id)
    if not result:
        await query.answer("No se encontró el registro", show_alert=True)
        return

    if result.get("boosted_at") and result.get("boosted") == 1:
        # Already boosted before this call — check if we just applied it
        original_text = query.message.text or ""
        if "🏆 TOP" in original_text:
            await query.answer("Ya está marcado como TOP", show_alert=True)
            return

    # Edit message to show TOP badge
    original_text = query.message.text or ""
    rating = result.get("rating", 0)
    top_text = original_text.replace(
        f"🎯 *Valoración:* {rating}/10",
        f"🏆 *TOP · Valoración:* {rating}/10",
    )
    if top_text == original_text:
        # Fallback: prepend TOP
        top_text = f"🏆 *TOP*\n\n{original_text}"

    try:
        await query.message.edit_text(
            text=top_text,
            parse_mode="Markdown",
        )
        logger.info(f"Boosted message {message_id} in chat {chat_id} (rating: {rating})")
    except Exception as e:
        logger.warning(f"Could not edit boosted message: {e}")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /top command — list top boosted content."""
    top_items = await storage.get_top(limit=10)
    if not top_items:
        await update.message.reply_text("No hay contenido TOP todavía. Usa el botón 🚀 Boost para marcar contenido.")
        return

    lines = ["🏆 *TOP Content*\n"]
    for i, item in enumerate(top_items, 1):
        rating = item.get("rating", 0)
        summary = item.get("summary", item.get("content", "")[:80])
        category = item.get("category", "otro").upper()
        stars = "⭐" * min(rating, 10)
        lines.append(f"{i}. *[{category}]* {rating}/10 {stars}")
        lines.append(f"   _{summary}_\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ranking command — show all rated content sorted by score."""
    items = await storage.get_ranking(limit=15)
    if not items:
        await update.message.reply_text("No hay contenido valorado todavía.")
        return

    lines = ["📊 *Ranking de contenido*\n"]
    for i, item in enumerate(items, 1):
        rating = item.get("rating", 0)
        boosted = item.get("boosted", 0)
        summary = item.get("summary", item.get("content", "")[:80])
        category = item.get("category", "otro").upper()
        author = item.get("author", "")
        stars = "⭐" * min(rating, 10)
        top_badge = "🏆 " if boosted else ""
        lines.append(f"{i}. {top_badge}*[{category}]* {rating}/10 {stars}")
        lines.append(f"   _{summary}_")
        lines.append(f"   — {author}\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    text = (
        "Memorizer - Tu asistente de memoria personal\n\n"
        "Envía cualquier mensaje al grupo y lo clasifico automáticamente.\n\n"
        "Comandos:\n"
        "/buscar <texto> - Buscar en tus memorias\n"
        "/resumen [dias] - Resumen de los últimos N días (default: 7)\n"
        "/stats - Estadísticas de memorias guardadas\n"
        "/ranking - Ver ranking de contenido por valoración\n"
        "/top - Ver solo contenido marcado como TOP\n"
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
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("ranking", cmd_ranking))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    # Boost callback
    app.add_handler(CallbackQueryHandler(handle_boost, pattern="^boost$"))

    # Capture all non-command messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Memorizer bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
