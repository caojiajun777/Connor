"""Public daily report API (read-only for the Connor.ai site)."""

from app.daily.public.api import create_public_router

__all__ = ["create_public_router"]
