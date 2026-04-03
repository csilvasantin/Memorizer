from src.config import (
    COUNCIL_MEMBERS,
    ROUTING_RULES,
    CATEGORY_DESTINATION,
    TELEGRAM_NEGOCIO_GROUP_ID,
    TELEGRAM_TECNOLOGIA_GROUP_ID,
    TELEGRAM_CREATIVIDAD_GROUP_ID,
    TELEGRAM_MISCELANEA_GROUP_ID,
)


_GROUP_MAP = {
    "negocio": TELEGRAM_NEGOCIO_GROUP_ID,
    "tecnologia": TELEGRAM_TECNOLOGIA_GROUP_ID,
    "creatividad": TELEGRAM_CREATIVIDAD_GROUP_ID,
    "miscelanea": TELEGRAM_MISCELANEA_GROUP_ID,
}


def get_destination_group(category: str) -> int:
    """Return the destination Telegram group ID for the given category."""
    key = CATEGORY_DESTINATION.get(category, "miscelanea")
    return _GROUP_MAP.get(key, 0)


def format_forwarded_message(
    category: str,
    content: str,
    summary: str,
    recipients: list[dict],
    author: str,
) -> str:
    """Format the message to send to the destination group."""
    category_meta = {
        "tecnología": ("🔧", "TECNOLOGÍA"),
        "trabajo": ("💼", "TRABAJO"),
        "creatividad": ("🎨", "CREATIVIDAD"),
        "idea": ("💡", "IDEA"),
        "negocio": ("📊", "NEGOCIO"),
        "referencia": ("📌", "REFERENCIA"),
        "contacto": ("📇", "CONTACTO"),
        "evento": ("📅", "EVENTO"),
        "otro": ("📝", "OTRO"),
        "personal": ("👤", "PERSONAL"),
    }
    emoji, label = category_meta.get(category, ("📝", category.upper()))

    lines = [f"{emoji} *[{label}]* — enviado por {author}", ""]

    if summary:
        lines.append(f"_{summary}_")
        lines.append("")

    # Trim long content
    display_content = content if len(content) <= 400 else content[:400] + "…"
    lines.append(display_content)

    if recipients:
        lines.append("")
        roles_str = ", ".join(r["role"] for r in recipients)
        sides = {r["side"] for r in recipients}
        if sides == {"left"}:
            side_label = "Lado izquierdo"
        elif sides == {"right"}:
            side_label = "Lado derecho"
        else:
            side_label = "Mesa completa"
        lines.append(f"👥 *Consejo ({side_label}):* {roles_str}")

    return "\n".join(lines)


def get_recipients(category: str) -> list[dict]:
    """Return list of council members who should receive content for the given category."""
    rule = ROUTING_RULES.get(category, ["none"])

    if "none" in rule:
        return []

    if "all" in rule:
        return [{"role": role, **info} for role, info in COUNCIL_MEMBERS.items()]

    recipients = []
    for side in rule:
        for role, info in COUNCIL_MEMBERS.items():
            if info["side"] == side:
                recipients.append({"role": role, **info})
    return recipients


def format_council_notification(category: str, summary: str, recipients: list[dict]) -> str:
    """Format a notification message for the group about council routing."""
    if not recipients:
        return ""

    roles = [r["role"] for r in recipients]
    sides = {r["side"] for r in recipients}

    # Pick emoji and label based on category
    category_meta = {
        "tecnología": ("🔧", "TECNOLOGÍA"),
        "trabajo": ("💼", "TRABAJO"),
        "creatividad": ("🎨", "CREATIVIDAD"),
        "idea": ("💡", "IDEA"),
        "negocio": ("📊", "NEGOCIO"),
        "referencia": ("📌", "REFERENCIA"),
        "contacto": ("📇", "CONTACTO"),
        "evento": ("📅", "EVENTO"),
    }
    emoji, label = category_meta.get(category, ("📝", category.upper()))

    roles_str = ", ".join(roles)

    if sides == {"left"}:
        side_label = "Lado izquierdo (operacional/racional)"
    elif sides == {"right"}:
        side_label = "Lado derecho (creativo)"
    else:
        side_label = "Mesa completa: todos los consejeros"

    lines = [
        f"{emoji} Contenido de *{label}* → {side_label}",
        f"*Consejeros:* {roles_str}",
    ]

    if summary:
        lines.append(f"_{summary}_")

    # List members with their current/legend names
    lines.append("")
    for r in recipients:
        lines.append(f"• *{r['role']}* — {r['current']} _(leyenda: {r['legend']})_")

    return "\n".join(lines)
