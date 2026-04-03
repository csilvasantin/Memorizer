import json
import logging
import re
from anthropic import AsyncAnthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CATEGORIES, SOURCE_KEYWORDS

logger = logging.getLogger(__name__)

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

CLASSIFY_PROMPT = """Eres un asistente que clasifica y extrae información de mensajes.

Dado el siguiente mensaje, devuelve un JSON con:
- "category": una de {categories}
- "summary": resumen en 1-2 frases (español)
- "entities": lista de entidades (personas, empresas, lugares) mencionadas
- "urls": lista de URLs encontradas
- "source_hint": si detectas de qué red social/plataforma viene (linkedin, whatsapp, twitter, instagram, email, web, unknown)

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


async def classify_message(content: str) -> dict:
    """Classify a message using Claude API and return structured data."""
    source = detect_source(content)
    urls = extract_urls(content)

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": CLASSIFY_PROMPT.format(
                        categories=", ".join(CATEGORIES),
                        message=content,
                    ),
                }
            ],
        )

        result = json.loads(response.content[0].text)

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
