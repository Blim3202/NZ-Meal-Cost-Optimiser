from supabase import create_client, Client
from core.config import settings


_client: Client | None = None
_publishable_client: Client | None = None
_warned = False


def _require_enabled() -> None:
    global _warned
    if not settings.supabase_enabled:
        if not _warned:
            _warned = True
        raise RuntimeError(
            "Supabase is not configured. Populate SUPABASE_URL + SUPABASE_SECRET_KEY "
            "(and SUPABASE_PUBLISHABLE_KEY) in scripts/fastapi/.env, or run in local-only "
            "fallback mode (no Supabase-dependent endpoints)."
        )


def get_supabase() -> Client:
    _require_enabled()
    global _client
    if _client is None:
        _client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SECRET_KEY,
        )
    return _client


def get_supabase_publishable() -> Client:
    _require_enabled()
    global _publishable_client
    if _publishable_client is None:
        _publishable_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_PUBLISHABLE_KEY,
        )
    return _publishable_client


def supabase_available() -> bool:
    """True if a usable service-role client can be constructed right now."""
    return settings.supabase_enabled
