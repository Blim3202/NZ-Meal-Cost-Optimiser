"""Path bootstrap for the FastAPI layer.

Inserts the legacy `scripts/*/` package directories onto `sys.path` so the
existing optimiser modules (`optimiser_utils`, `woolworths_api`,
`paknsave_api`, `newworld_api`, etc.) remain importable — no source files modified.
"""
import sys
from pathlib import Path

FASTAPI_DIR = Path(__file__).resolve().parent.parent  # scripts/fastapi
SCRIPTS_DIR = FASTAPI_DIR.parent                       # scripts
COMBINED_DIR = SCRIPTS_DIR / "combined"
WOOLWORTHS_DIR = SCRIPTS_DIR / "woolworths"
PAKNSAVE_DIR = SCRIPTS_DIR / "paknsave"
NEWWORLD_DIR = SCRIPTS_DIR / "newworld"
DATA_DIR = SCRIPTS_DIR.parent / "data"                 # project/data

_PATHS = [str(FASTAPI_DIR), str(COMBINED_DIR), str(WOOLWORTHS_DIR), str(PAKNSAVE_DIR), str(NEWWORLD_DIR)]

def bootstrap() -> None:
    for p in _PATHS:
        if p not in sys.path:
            sys.path.insert(0, p)

bootstrap()
