from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.db.database import DATABASE_URL, database_status, init_database


def safe_url_label(url: str) -> str:
    if url.startswith("postgresql"):
        return "PostgreSQL (credentials hidden)"
    if url.startswith("sqlite"):
        return "SQLite local fallback"
    return "Configured database (credentials hidden)"


if __name__ == "__main__":
    init_database()
    status = database_status()
    print("ANTARCTIC NAV-X database initialization")
    print("Database:", safe_url_label(DATABASE_URL))
    print("Reachable:", status.get("reachable"))
    print("Backend:", status.get("backend"))
    if not status.get("reachable"):
        print("Error:", status.get("error"))
        raise SystemExit(1)
    print("Tables created/verified successfully.")
