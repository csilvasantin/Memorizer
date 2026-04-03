import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from anthropic import AsyncAnthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CATEGORIES, SOURCE_KEYWORDS

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

logger = logging.getLogger(__name__)

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

CLASSIFY_PROMPT = """Eres un asistente que clasifica y extrae información de mensajes para el Consejo de Admira Next.

Dado el siguiente mensaje, devuelve un JSON con:
- "category": una de {categories}
- "summary": resumen en 1-2 frases (español)
- "entities": lista de entidades (personas, empresas, lugares) mencionadas
- "urls": lista de URLs encontradas
- "source_hint": si detectas de qué red social/plataforma viene (linkedin, whatsapp, twitter, instagram, email, web, youtube, unknown)
- "review": (SOLO si el contenido es un video de YouTube u otro contenido multimedia con metadatos disponibles) un objeto con:
  - "rating": puntuación del 1 al 10 según relevancia para una empresa de tecnología creativa
  - "verdict": valoración en 1-2 frases: qué aporta, para quién es útil, qué se puede aprender
  - "tags": lista de 2-4 etiquetas temáticas (ej: "liderazgo", "IA", "diseño", "startups")

Guía para elegir la categoría correcta:
- "tecnología": artículos, noticias, herramientas, productos o tendencias tecnológicas (IA, software, hardware, startups tech)
- "creatividad": contenido sobre diseño, arte, storytelling, branding, experiencias, publicidad creativa, arquitectura, moda
- "negocio": estrategia empresarial, mercados, finanzas, inversión, management, liderazgo, industria
- "trabajo": tareas, proyectos, reuniones, pendientes laborales (no es contenido externo, es acción interna)
- "idea": ocurrencias propias, brainstorming, conceptos nuevos sin desarrollar
- "referencia": artículos de consulta, documentación, libros, recursos de aprendizaje general
- "contacto": datos de personas, tarjetas, perfiles
- "evento": conferencias, meetups, fechas importantes, citas
- "personal": notas privadas, recordatorios personales, vida cotidiana
- "otro": cualquier cosa que no encaje en las anteriores

Guía para la valoración (review):
- Valora desde la perspectiva de Admira Next, una empresa de tecnología creativa y digital signage
- Un 10 es contenido directamente aplicable al negocio o con insights transformadores
- Un 7-9 es contenido muy relevante para el equipo directivo
- Un 4-6 es contenido interesante pero tangencial
- Un 1-3 es contenido con poca relevancia para el equipo

Responde SOLO con el JSON, sin texto adicional.

Mensaje:
{message}"""


def detect_source(text: str) -> str:
    text_lower = text.lower()
    for source, keywords in SOURCE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return source
    return "unknown"


def extract_urls(text: str) -> list[str]:
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


_yt_executor = ThreadPoolExecutor(max_workers=1)
_YT_PATTERN = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+')


def _fetch_youtube_meta(url: str) -> dict | None:
    """Fetch title and description from a YouTube URL using yt_dlp."""
    if not yt_dlp:
        return None
    try:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title", ""),
                "description": (info.get("description") or "")[:500],
            }
    except Exception as e:
        logger.warning(f"Could not fetch YouTube metadata for {url}: {e}")
        return None


def _enrich_with_youtube_sync(content: str) -> str:
    """If content is mostly a YouTube URL, fetch metadata and enrich it."""
    urls = _YT_PATTERN.findall(content)
    if not urls:
        return content

    enriched = content
    for url in urls[:2]:  # max 2 videos per message
        meta = _fetch_youtube_meta(url)
        if meta and meta["title"]:
            enriched += f"\n\n[Contenido del video: {meta['title']}]\n{meta['description'][:300]}"
    return enriched


async def _enrich_with_youtube(content: str) -> str:
    """Async wrapper — runs yt_dlp in a thread to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_yt_executor, _enrich_with_youtube_sync, content)


async def classify_message(content: str) -> dict:
    """Classify a message using Claude API and return structured data."""
    source = detect_source(content)
    urls = extract_urls(content)

    # Enrich YouTube links with video metadata for better classification
    enriched_content = await _enrich_with_youtube(content)
    if enriched_content != content:
        logger.info(f"YouTube enriched: {enriched_content[:200]}...")

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": CLASSIFY_PROMPT.format(
                        categories=", ".join(CATEGORIES),
                        message=enriched_content,
                    ),
                }
            ],
        )

        raw_text = response.content[0].text
        # Strip markdown code fences if present
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        result = json.loads(cleaned)

        # Use local detection as fallback
        if result.get("source_hint") == "unknown" and source != "unknown":
            result["source_hint"] = source
        if not result.get("urls") and urls:
            result["urls"] = urls

        return {
            "category": result.get("category", "otro"),
            "summary": result.get("summary", ""),
            "entities": result.get("entities", []),
            "urls": result.get("urls", urls),
            "source": result.get("source_hint", source),
            "review": result.get("review"),
        }
    except Exception as e:
        logger.warning(f"Classification failed, using fallback: {e}")
        # Fallback: basic classification without AI
        return {
            "category": "otro",
            "summary": content[:100],
            "entities": [],
            "urls": urls,
            "source": source,
            "error": str(e),
        }
