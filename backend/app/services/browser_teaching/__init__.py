"""Hosted browser teaching, slice 1: lease-bound structural capture and retention (#113).

Routes and the worker import only from here.
"""

from app.services.browser_teaching._capture import HoldCapture, attach
from app.services.browser_teaching._service import BrowserTeachingService
from app.services.browser_teaching._sweep import sweep_browser_teachings

__all__ = ["BrowserTeachingService", "HoldCapture", "attach", "sweep_browser_teachings"]
