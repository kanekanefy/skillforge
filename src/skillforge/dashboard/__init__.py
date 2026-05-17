"""Local dashboard server.

A small Flask app rendering server-side HTML for browsing your skill
library, metrics, queue, and recordings. We use stdlib `http.server` +
hand-rolled HTML rather than Flask/Jinja to avoid pulling in a web
framework — `sf dash` should start in <500ms with zero install warmup.
"""

from .server import run as run_dashboard

__all__ = ["run_dashboard"]
