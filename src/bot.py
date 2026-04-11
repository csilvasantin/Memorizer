from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReactionTypeEmoji
from telegram.constants import ParseMode
from telegram.error import BadRequest
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
from src.yarig import YarigClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

storage = MemoryStorage()
yarig = YarigClient()

NOTIFICATION_SOUND = os.path.expanduser("~/Library/Sounds/notification.wav")
YARIG_AUTOREFRESH_SECONDS = 5 * 60
_yarig_autorefresh_tasks: dict[tuple[int, int], asyncio.Task] = {}


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


def _task_sort_key(task: dict) -> tuple[int, str]:
    finished = task.get("finished", "0") == "1"
    started = bool(task.get("start_time"))
    ended = bool(task.get("end_time"))
    if started and not ended and not finished:
        rank = 0
    elif not started and not finished:
        rank = 1
    elif started and ended and not finished:
        rank = 2
    else:
        rank = 3
    return rank, str(task.get("description", "")).lower()


def _yarig_panel_key(chat_id: int, message_id: int) -> tuple[int, int]:
    return chat_id, message_id


def _is_yarig_autorefresh_enabled(chat_id: int, message_id: int) -> bool:
    key = _yarig_panel_key(chat_id, message_id)
    task = _yarig_autorefresh_tasks.get(key)
    if task is None:
        return False
    if task.done():
        _yarig_autorefresh_tasks.pop(key, None)
        return False
    return True


def _cancel_yarig_autorefresh(chat_id: int, message_id: int) -> bool:
    task = _yarig_autorefresh_tasks.pop(_yarig_panel_key(chat_id, message_id), None)
    if task is None:
        return False
    task.cancel()
    return True


async def _send_text(target, text: str, *, edit: bool = False, parse_mode: str | None = ParseMode.MARKDOWN, reply_markup=None):
    sender = target.edit_text if edit else target.reply_text
    kwargs = {"text": text, "reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    try:
        return await sender(**kwargs)
    except BadRequest as exc:
        message = str(exc)
        if edit and "Message is not modified" in message:
            return None
        if parse_mode is not None and "parse entities" in message.lower():
            return await sender(text=text, reply_markup=reply_markup)
        raise


async def _ensure_yarig_configured(message) -> bool:
    if yarig.credentials_configured():
        return True
    await _send_text(
        message,
        "⚠️ Faltan `YARIG_EMAIL` y/o `YARIG_PASSWORD` en el `.env` de Memorizer.",
    )
    return False


async def _edit_message_text(bot, chat_id: int, message_id: int, text: str, *, parse_mode: str | None = ParseMode.MARKDOWN, reply_markup=None):
    kwargs = {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    try:
        return await bot.edit_message_text(**kwargs)
    except BadRequest as exc:
        message = str(exc)
        if "Message is not modified" in message:
            return None
        if parse_mode is not None and "parse entities" in message.lower():
            return await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
        raise


async def _get_yarig_panel_view(*, autorefresh_enabled: bool = False) -> tuple[str, InlineKeyboardMarkup, str | None]:
    if not yarig.credentials_configured():
        return (
            "⚠️ Faltan `YARIG_EMAIL` y/o `YARIG_PASSWORD` en el `.env` de Memorizer.",
            _build_task_keyboard([], autorefresh_enabled=autorefresh_enabled),
            ParseMode.MARKDOWN,
        )

    data = await yarig.get_today_data()
    keyboard = _build_task_keyboard(
        data.get("tasks", []) if data else [],
        autorefresh_enabled=autorefresh_enabled,
    )
    if not data:
        return yarig.operation_error("cargar el panel de Yarig.ai"), keyboard, None

    summary = await yarig.get_today_summary(data)
    return summary, keyboard, ParseMode.MARKDOWN


async def _run_yarig_autorefresh(application: Application, chat_id: int, message_id: int) -> None:
    key = _yarig_panel_key(chat_id, message_id)
    try:
        while True:
            await asyncio.sleep(YARIG_AUTOREFRESH_SECONDS)
            try:
                text, keyboard, parse_mode = await _get_yarig_panel_view(autorefresh_enabled=True)
                await _edit_message_text(
                    application.bot,
                    chat_id,
                    message_id,
                    text,
                    parse_mode=parse_mode,
                    reply_markup=keyboard,
                )
            except asyncio.CancelledError:
                raise
            except BadRequest as exc:
                error = str(exc).lower()
                if "message to edit not found" in error or "message can't be edited" in error:
                    logger.info(f"Stopping Yarig auto-refresh for missing/uneditable message {chat_id}:{message_id}")
                    break
                logger.warning(f"Yarig auto-refresh edit failed for {chat_id}:{message_id}: {exc}")
            except Exception:
                logger.exception(f"Error auto-refreshing Yarig panel {chat_id}:{message_id}")
    except asyncio.CancelledError:
        logger.info(f"Cancelled Yarig auto-refresh for {chat_id}:{message_id}")
        raise
    finally:
        current = _yarig_autorefresh_tasks.get(key)
        if current is asyncio.current_task():
            _yarig_autorefresh_tasks.pop(key, None)


def _start_yarig_autorefresh(application: Application, chat_id: int, message_id: int) -> None:
    _cancel_yarig_autorefresh(chat_id, message_id)
    key = _yarig_panel_key(chat_id, message_id)
    _yarig_autorefresh_tasks[key] = asyncio.create_task(
        _run_yarig_autorefresh(application, chat_id, message_id),
        name=f"yarig-autorefresh-{chat_id}-{message_id}",
    )


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


async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle noop button press (task name, no action)."""
    await update.callback_query.answer()


async def handle_yarig_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Yarig task control buttons."""
    query = update.callback_query
    action = query.data or ""
    message = query.message

    if message is None:
        await query.answer()
        return

    chat_id = message.chat_id
    message_id = message.message_id

    if action == "yt_refresh":
        await query.answer("Actualizando...")
        await _send_yarig_panel(message, edit=True)
        return

    if action == "yt_autorefresh":
        if _is_yarig_autorefresh_enabled(chat_id, message_id):
            _cancel_yarig_autorefresh(chat_id, message_id)
            await query.answer("Auto-refresh desactivado")
        else:
            _start_yarig_autorefresh(context.application, chat_id, message_id)
            await query.answer("Auto-refresh activado cada 5 min")
        await _send_yarig_panel(message, edit=True)
        return

    if not await _ensure_yarig_configured(message):
        await query.answer("Faltan credenciales de Yarig", show_alert=True)
        return

    if action.startswith("yt_pause_"):
        task_id = action.split("_")[-1]
        await query.answer("Pausando tarea...")
        result = await yarig.pausar_tarea_por_id(task_id)
        logger.info(f"Yarig pause: {result}")
        await _send_yarig_panel(message, edit=True)
        return

    if action.startswith("yt_start_"):
        task_id = action.split("_")[-1]
        await query.answer("Iniciando tarea...")
        result = await yarig.iniciar_tarea_por_id(task_id)
        logger.info(f"Yarig start {task_id}: {result}")
        await _send_yarig_panel(message, edit=True)
        return

    if action.startswith("yt_finish_"):
        task_id = action.split("_")[-1]
        await query.answer("Finalizando tarea...")
        result = await yarig.finalizar_tarea_por_id(task_id)
        logger.info(f"Yarig finish {task_id}: {result}")
        await _send_yarig_panel(message, edit=True)
        return

    await query.answer()


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


def _build_task_keyboard(tasks: list[dict], *, autorefresh_enabled: bool = False) -> InlineKeyboardMarkup:
    """Build inline keyboard with task controls."""
    rows = []
    ordered_tasks = sorted(tasks, key=_task_sort_key)
    for i, task in enumerate(ordered_tasks, 1):
        desc = task.get("description", "").strip()[:25]
        task_id = str(task.get("id", "")).strip()
        finished = task.get("finished", "0")
        started = task.get("start_time") is not None
        active = started and not task.get("end_time") and finished == "0"

        if finished == "1":
            # Completed — no controls
            rows.append([InlineKeyboardButton(f"✅ {i}. {desc}", callback_data="noop")])
        elif active:
            # Active — show pause + finish
            rows.append([
                InlineKeyboardButton(f"🟢 {i}. {desc}", callback_data="noop"),
                InlineKeyboardButton("⏸️", callback_data=f"yt_pause_{task_id}"),
                InlineKeyboardButton("✅", callback_data=f"yt_finish_{task_id}"),
            ])
        elif started:
            # Paused — show resume + finish
            rows.append([
                InlineKeyboardButton(f"⏸️ {i}. {desc}", callback_data="noop"),
                InlineKeyboardButton("▶️", callback_data=f"yt_start_{task_id}"),
                InlineKeyboardButton("✅", callback_data=f"yt_finish_{task_id}"),
            ])
        else:
            # Pending — show start
            rows.append([
                InlineKeyboardButton(f"🕓 {i}. {desc}", callback_data="noop"),
                InlineKeyboardButton("▶️", callback_data=f"yt_start_{task_id}"),
            ])

    auto_label = "🟢 Auto 5m" if autorefresh_enabled else "✨ Auto 5m"
    rows.append([
        InlineKeyboardButton("🔄 Actualizar", callback_data="yt_refresh"),
        InlineKeyboardButton(auto_label, callback_data="yt_autorefresh"),
    ])
    return InlineKeyboardMarkup(rows)


async def _send_yarig_panel(message, edit: bool = False):
    """Send or edit the Yarig task panel with inline controls."""
    autorefresh_enabled = False
    if edit and message is not None:
        autorefresh_enabled = _is_yarig_autorefresh_enabled(message.chat_id, message.message_id)

    try:
        text, keyboard, parse_mode = await _get_yarig_panel_view(autorefresh_enabled=autorefresh_enabled)
        await _send_text(message, text, edit=edit, parse_mode=parse_mode, reply_markup=keyboard)
    except Exception:
        logger.exception("Error building Yarig panel")
        await _send_text(
            message,
            "⚠️ Falló el panel de Yarig en Memorizer. Revisa credenciales, sesión o logs e inténtalo otra vez.",
            edit=edit,
            parse_mode=None,
            reply_markup=_build_task_keyboard([], autorefresh_enabled=autorefresh_enabled),
        )


def _yarig_result_should_return_to_panel(result: str) -> bool:
    return result.startswith(("✅", "🔄", "▶️", "⏸"))


async def cmd_yarig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /yarig command — show today's tasks with controls."""
    message = update.effective_message
    if not message:
        return
    await _send_yarig_panel(message)


async def cmd_fichar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fichar command — clock in or out."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    arg = " ".join(context.args).strip().lower() if context.args else ""
    if arg in ("salida", "out", "fin"):
        result = await yarig.fichar_salida()
    else:
        result = await yarig.fichar_entrada()
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_tarea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tarea command — add a new task."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    if not context.args:
        await _send_text(message, "Uso: /tarea <descripción>\nEjemplo: /tarea Revisar diseño del dashboard", parse_mode=None)
        return
    desc = " ".join(context.args)
    result = await yarig.add_task(desc)
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /iniciar command — start or resume a task by index."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    idx = 1
    if context.args:
        try:
            idx = int(context.args[0])
        except ValueError:
            pass
    result = await yarig.iniciar_tarea(idx)
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_pausar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pausar command — pause the active task (leave for later)."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    result = await yarig.pausar_tarea()
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /finalizar command — mark task as completed."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    idx = None
    if context.args:
        try:
            idx = int(context.args[0])
        except ValueError:
            pass
    result = await yarig.finalizar_tarea(idx)
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /score command — show Yarig score."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    result = await yarig.get_score()
    await _send_text(message, result)


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /historial command — show task history."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    result = await yarig.get_history()
    await _send_text(message, result)


async def cmd_extras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /extras command — start or stop overtime."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    arg = " ".join(context.args).strip().lower() if context.args else ""
    if arg in ("fin", "stop", "parar"):
        result = await yarig.extras_fin()
    else:
        result = await yarig.extras_inicio()
    await _send_text(message, result, parse_mode=None)
    if _yarig_result_should_return_to_panel(result):
        await _send_yarig_panel(message)


async def cmd_equipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /equipo command — show team members."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    result = await yarig.get_team()
    await _send_text(message, result)


async def cmd_pedir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pedir command — send task request to a teammate."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    if not context.args or len(context.args) < 2:
        await _send_text(
            message,
            "Uso: /pedir <nombre> <descripción>\n"
            "Ejemplo: /pedir David Revisar el presupuesto Q2",
            parse_mode=None,
        )
        return

    name = context.args[0]
    text = " ".join(context.args[1:])

    mate = await yarig.find_mate(name)
    if not mate:
        await _send_text(message, f"No encontré a '{name}' en el equipo", parse_mode=None)
        return

    result = await yarig.send_request(mate["user_id"], text)
    await _send_text(message, f"{result}\n🤝 Enviada a *{mate['name']}*")


async def cmd_proyectos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /proyectos command — list projects."""
    message = update.effective_message
    if not message or not await _ensure_yarig_configured(message):
        return
    result = await yarig.list_projects()
    await _send_text(message, result)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    text = (
        "🧠 *Memorizer* · tu asistente de productividad\n\n"
        "*🗂️ Yarig.ai · Tareas*\n"
        "/yarig — Abrir el panel del día\n"
        "/tarea <desc> — Añadir tarea\n"
        "/iniciar [n] — Iniciar o reanudar tarea\n"
        "/pausar — Pausar tarea\n"
        "/finalizar [n] — Completar tarea\n\n"
        "*🕘 Yarig.ai · Jornada*\n"
        "/fichar — Fichar entrada\n"
        "/fichar salida — Fichar salida\n"
        "/extras — Iniciar horas extras\n"
        "/extras fin — Finalizar horas extras\n\n"
        "*🤝 Yarig.ai · Equipo*\n"
        "/score — Ver tu puntuación\n"
        "/equipo — Ver el equipo\n"
        "/pedir <nombre> <tarea> — Pedir tarea\n"
        "/proyectos — Ver proyectos\n"
        "/historial — Ver historial de tareas\n\n"
        "*🔎 Memorizer · Contenido*\n"
        "/buscar <texto> — Buscar en memorias\n"
        "/resumen [dias] — Resumen de N días\n"
        "/stats — Ver estadísticas\n"
        "/ranking — Ver ranking de contenido\n"
        "/top — Ver contenido TOP\n\n"
        "/help — Ver esta ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def post_init(application: Application):
    """Initialize database on startup."""
    await storage.init_db()
    logger.info("Database initialized")
    if not yarig.credentials_configured():
        logger.warning("YARIG_EMAIL/YARIG_PASSWORD are not configured in Memorizer")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log unexpected errors and send a visible fallback to Telegram."""
    logger.exception("Unhandled bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await _send_text(
                update.effective_message,
                "⚠️ El comando falló dentro de Memorizer. Revisa logs o configuración e inténtalo de nuevo.",
                parse_mode=None,
            )
        except Exception:
            logger.exception("Could not send error message back to Telegram")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set. Check your .env file.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands — Memorizer
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("ranking", cmd_ranking))

    # Commands — Yarig.ai
    app.add_handler(CommandHandler("yarig", cmd_yarig))
    app.add_handler(CommandHandler("fichar", cmd_fichar))
    app.add_handler(CommandHandler("tarea", cmd_tarea))
    app.add_handler(CommandHandler("iniciar", cmd_iniciar))
    app.add_handler(CommandHandler("pausar", cmd_pausar))
    app.add_handler(CommandHandler("finalizar", cmd_finalizar))
    app.add_handler(CommandHandler("score", cmd_score))
    app.add_handler(CommandHandler("historial", cmd_historial))
    app.add_handler(CommandHandler("extras", cmd_extras))
    app.add_handler(CommandHandler("equipo", cmd_equipo))
    app.add_handler(CommandHandler("pedir", cmd_pedir))
    app.add_handler(CommandHandler("proyectos", cmd_proyectos))

    # General
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_boost, pattern="^boost$"))
    app.add_handler(CallbackQueryHandler(handle_yarig_control, pattern="^yt_"))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern="^noop$"))

    # Capture all non-command messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    async def _shutdown(_: Application) -> None:
        for task in list(_yarig_autorefresh_tasks.values()):
            task.cancel()
        await yarig.close()

    app.post_shutdown = _shutdown

    logger.info("Memorizer bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
