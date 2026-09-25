from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.ml.train_all import train_ais

if __name__ == "__main__":
    result = train_ais(force=True)
    print(json.dumps(result, indent=2, default=str))
