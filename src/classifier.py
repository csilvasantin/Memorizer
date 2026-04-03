import json
import re
from anthropic import AsyncAnthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CATEGORIES, SOURCE_KEYWORDS

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

CLASSIFY_PROMPT = """Eres un asistente que clasifica y extrae información de mensajes personales guardados por el usuario.

Dado el siguiente mensaje, devuelve un JSON con:
- "category": una de {categories}
- "summary": resumen en 1-2 frases (español)
- "entities": lista de entidades (personas, empresas, lugares) mencionadas
- "urls": lista de URLs encontradas
- "source_hint": si detectas de qué red social/plataforma viene (linkedin, whatsapp, twitter, instagram, email, web, unknown)

REGLAS ESTRICTAS PARA LA CATEGORÍA:
- "trabajo": SOLO si el mensaje es claramente sobre trabajo del usuario (tareas laborales, reuniones de trabajo, proyectos profesionales, decisiones de negocio propias). NO incluye noticias de empresas ni economía general.
- "personal": SOLO si el mensaje es claramente sobre la vida personal del usuario (salud propia, familia, amigos, relaciones, finanzas personales).
- "referencia": SOLO si el mensaje es un recurso técnico, artículo educativo o documentación que el usuario guardó para consultar (tutoriales, documentación, guías técnicas). NO incluye noticias generales.
- "idea": SOLO si el mensaje contiene una idea original del usuario o una idea específica que quiere desarrollar.
- "contacto": SOLO si el mensaje es sobre una persona específica con quien el usuario tiene o quiere tener relación directa.
- "evento": SOLO si el mensaje es sobre un evento al que el usuario va a asistir o que le afecta directamente.
- "otro": USA ESTA CATEGORÍA POR DEFECTO cuando no estés seguro. Incluye SIEMPRE: noticias políticas, noticias generales, deportes, chismes de entretenimiento, artículos de opinión, noticias de tecnología sin relación directa al trabajo del usuario, noticias económicas generales, contenido viral, memes, y cualquier contenido que no encaje CLARAMENTE en las categorías anteriores.

EN CASO DE DUDA, USA "otro". Es mejor clasificar de más en "otro" que poner contenido en una categoría incorrecta.

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
        # Fallback: basic classification without AI
        return {
            "category": "otro",
            "summary": content[:100],
            "entities": [],
            "urls": urls,
            "source": source,
            "error": str(e),
        }
