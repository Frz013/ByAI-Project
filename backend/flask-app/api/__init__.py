"""
API package containing modularized feature blueprints for the Flask app.
Exposes:
- health_bp
- library_bp
- kbbi_bp
- ytdl_bp
"""

from .health import health_bp  # noqa: F401
from .library import library_bp  # noqa: F401
from .kbbi import kbbi_bp  # noqa: F401
from .ytdl import ytdl_bp  # noqa: F401

__all__ = ["health_bp", "library_bp", "kbbi_bp", "ytdl_bp"]
