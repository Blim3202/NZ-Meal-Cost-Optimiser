"""workers package — Phase 2 queued optimizer workers.

Importing this package runs the path bootstrap (so legacy optimizer modules
resolve), then worker submodules are importable.
"""
from core.paths import bootstrap  # noqa: F401  (side-effect: sys.path setup)
