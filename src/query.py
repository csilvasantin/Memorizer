import json
from datetime import datetime, timedelta
from anthropic import AsyncAnthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.storage import MemoryStorage

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
storage = MemoryStorage()

QUERY_PROMPT = """Eres Memorizer, un asistente personal de memoria.
Tienes acceso al historial de información que el usuario ha guardado.

Contexto recuperado de la base de datos:
{context}

Pregunta del usuario: {query}

Responde de forma concisa y útil en español. Si la información no está en el contexto,
dilo claramente. Incluye fechas y fuentes cuando sea relevante."""

SUMMARY_PROMPT = """Eres Memorizer, un asistente personal de memoria.
Genera un resumen organizado por categorías de la siguiente información recopilada:

{context}

Periodo: {period}

Organiza el resumen por categorías (trabajo, personal, ideas, etc.).
Sé conciso pero incluye los puntos clave. Responde en español."""


async def answer_query(query: str) -> str:
    """Search memories and answer a question using Claude."""
    results = await storage.search(query, limit=15)

    if not results:
        # Try with recent memories as fallback
        results = await storage.get_recent(limit=20)

    if not results:
        return "No tengo información guardada todavía. Envía mensajes al grupo para que los pueda organizar."

    context = _format_results(results)

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": QUERY_PROMPT.format(context=context, query=query),
            }
        ],
    )
    return response.content[0].text


async def generate_summary(days: int = 7) -> str:
    """Generate a summary of recent memories."""
    end = datetime.now().isoformat()
    start = (datetime.now() - timedelta(days=days)).isoformat()
    results = await storage.get_by_date_range(start, end)

    if not results:
        return f"No hay información guardada en los últimos {days} días."

    context = _format_results(results)
    period = f"Últimos {days} días (hasta {datetime.now().strftime('%d/%m/%Y')})"

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": SUMMARY_PROMPT.format(context=context, period=period),
            }
        ],
    )
    return response.content[0].text


async def get_stats_text() -> str:
    """Get formatted stats about stored memories."""
    stats = await storage.get_stats()
    lines = [f"Total de memorias: {stats['total']}"]

    if stats["by_category"]:
        lines.append("\nPor categoría:")
        for cat, count in stats["by_category"].items():
            lines.append(f"  - {cat}: {count}")

    if stats["by_source"]:
        lines.append("\nPor fuente:")
        for src, count in stats["by_source"].items():
            lines.append(f"  - {src}: {count}")

    return "\n".join(lines)


def _format_results(results: list[dict]) -> str:
    entries = []
    for r in results:
        date = r.get("created_at", "?")
        source = r.get("source", "?")
        cat = r.get("category", "?")
        summary = r.get("summary") or r.get("content", "")[:200]
        entries.append(f"[{date}] [{source}] [{cat}] {summary}")
    return "\n".join(entries)
