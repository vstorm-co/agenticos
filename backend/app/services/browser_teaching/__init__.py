"""Hosted browser teaching (#113): lease-bound structural capture, retention, review and one proposal.

Routes and the worker import only from here.
"""

from app.services.browser_teaching._capture import HoldCapture, attach
from app.services.browser_teaching._jobs import build_teaching_proposal
from app.services.browser_teaching._service import BrowserTeachingService
from app.services.browser_teaching._sweep import sweep_browser_teachings

__all__ = [
    "BrowserTeachingService",
    "HoldCapture",
    "attach",
    "build_teaching_proposal",
    "sweep_browser_teachings",
]
