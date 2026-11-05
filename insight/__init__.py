"""Insight by 50N Systems: on-board monitoring and diagnostics for yacht IT systems."""

import os

# Release images set INSIGHT_VERSION from the build's VERSION argument.
__version__ = os.environ.get("INSIGHT_VERSION") or "0.1.0"
