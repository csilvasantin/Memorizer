import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "0"))

# Destination groups
TELEGRAM_NEGOCIO_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_NEGOCIO", "0"))
TELEGRAM_TECNOLOGIA_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_TECNOLOGIA", "0"))
TELEGRAM_CREATIVIDAD_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_CREATIVIDAD", "0"))
TELEGRAM_MISCELANEA_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_MISCELANEA", "0"))

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Database
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "memorizer.db"))

# Categories for classification
CATEGORIES = [
    "trabajo",
    "personal",
    "referencia",
    "idea",
    "contacto",
    "evento",
    "otro",
    "tecnología",
    "creatividad",
    "negocio",
]

# Admira Next Board of Directors (Consejo)
COUNCIL_MEMBERS = {
    "CEO": {"legend": "Steve Jobs", "current": "Elon Musk", "side": "left"},
    "CFO": {"legend": "Warren Buffett", "current": "Ruth Porat", "side": "left"},
    "COO": {"legend": "Tim Cook", "current": "Gwynne Shotwell", "side": "left"},
    "CTO": {"legend": "Steve Wozniak", "current": "Jensen Huang", "side": "left"},
    "CCO": {"legend": "Walt Disney", "current": "John Lasseter", "side": "right"},
    "CSO": {"legend": "George Lucas", "current": "Ryan Reynolds", "side": "right"},
    "CXO": {"legend": "Es Devlin", "current": "Carlo Ratti", "side": "right"},
    "CDO": {"legend": "Dieter Rams", "current": "Jony Ive", "side": "right"},
}

# Destination group per category (resolved after group IDs are loaded)
# Keys match category names; value is one of the TELEGRAM_*_GROUP_ID constants
CATEGORY_DESTINATION = {
    "negocio": "negocio",
    "tecnología": "tecnologia",
    "creatividad": "creatividad",
    "otro": "miscelanea",
    "referencia": "negocio",
    "contacto": "negocio",
    "evento": "negocio",
    "trabajo": "negocio",
    "idea": "creatividad",
    "personal": "miscelanea",
}

# Routing rules: category -> list of sides ("left", "right") or "all" or "none"
ROUTING_RULES = {
    "tecnología": ["left"],
    "trabajo": ["left"],
    "creatividad": ["right"],
    "idea": ["right"],
    "negocio": ["all"],
    "referencia": ["all"],
    "contacto": ["all"],
    "evento": ["all"],
    "otro": ["none"],
    "personal": ["none"],
}

# Source detection keywords
SOURCE_KEYWORDS = {
    "linkedin": ["linkedin", "li://"],
    "whatsapp": ["whatsapp", "wa.me"],
    "twitter": ["twitter", "x.com", "tweet"],
    "instagram": ["instagram", "ig://"],
    "email": ["email", "correo", "mail"],
    "web": ["http://", "https://"],
}
