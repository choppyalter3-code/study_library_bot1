import re
from typing import List

from app.models import Material


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_material_text(material: Material, db) -> str:
    safe_title = escape_html(material.title)
    safe_desc = escape_html(material.description)
    safe_tags = escape_html(material.tags)
    safe_link = escape_html(material.link)

    category = db.get_category(material.category_id)
    if category:
        icon = category.icon
        name = category.name
    else:
        icon = "📂"
        name = "Материалы"

    lines = [
        f"{icon} <b>{name}</b>",
        "",
        f"<b>{safe_title}</b>",
        "",
        f"{safe_desc}",
        "",
        f"🔗 {safe_link}",
        f"🏷 {safe_tags}",
    ]

    return "\n".join(lines)


def normalize_tags(raw: str) -> str:
    tokens = re.split(r"[,\s]+", raw.strip())
    cleaned: List[str] = []
    for token in tokens:
        t = token.strip()
        if not t:
            continue
        if t.startswith("#"):
            t = t[1:]
        t = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]+", "", t)
        if not t:
            continue
        cleaned.append(f"#{t.lower()}")
    if not cleaned:
        return "#без_тегов"

    unique: List[str] = []
    seen = set()
    for item in cleaned:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return " ".join(unique)
