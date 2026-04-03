import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "0"))

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
]

# Source detection keywords
SOURCE_KEYWORDS = {
    "linkedin": ["linkedin", "li://"],
    "whatsapp": ["whatsapp", "wa.me"],
    "twitter": ["twitter", "x.com", "tweet"],
    "instagram": ["instagram", "ig://"],
    "email": ["email", "correo", "mail"],
    "web": ["http://", "https://"],
}
