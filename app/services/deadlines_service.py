from datetime import datetime
from typing import Optional


def parse_deadline_date(raw_date: str, now: Optional[datetime] = None) -> Optional[str]:
    text = raw_date.strip()
    if not text:
        return None

    current = now or datetime.utcnow()

    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass

    try:
        parsed = datetime.strptime(text, "%d.%m").date()
    except ValueError:
        return None

    candidate = parsed.replace(year=current.year)
    if candidate < current.date():
        candidate = candidate.replace(year=current.year + 1)
    return candidate.isoformat()


def format_deadline_date(iso_date: str) -> str:
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return iso_date
