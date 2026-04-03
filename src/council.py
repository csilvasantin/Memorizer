from src.config import COUNCIL_MEMBERS, ROUTING_RULES


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
