"""Path bootstrap for the FastAPI layer.

Inserts the legacy `scripts/*/` package directories onto `sys.path` so the
existing optimizer modules (`optimizer_utils`, `woolworths_optimizer`,
`paknsave_api`, `newworld_api`, etc.) remain importable as top-level modules
— exactly how their CLI thin-wrappers already load them. No project source
files are modified; this only reconciles import paths for the FastAPI side.
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

_PATHS = [FASTAPI_DIR, COMBINED_DIR, WOOLWORTHS_DIR, PAKNSAVE_DIR, NEWWORLD_DIR]


def bootstrap() -> None:
    for p in _PATHS:
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


# Auto-run on import so any `import core.paths` / `import workers` is sufficient.
bootstrap()
