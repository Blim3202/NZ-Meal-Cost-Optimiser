"""NZMealOptimiser package.

Provides per-brand price APIs (``pricing``), the LLM ingredient pipeline
(``llm``) and the FastAPI dashboard (``web``).

``PROJECT_ROOT`` and ``DATA_DIR`` are resolved here once so all modules can
share a single path contract regardless of where the package is installed.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

__all__ = ["PROJECT_ROOT", "DATA_DIR"]