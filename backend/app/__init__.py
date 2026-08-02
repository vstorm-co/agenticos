"""OS for your agents."""

from importlib.metadata import version

# The one place a version is written down. It used to be written in three -
# here, `main.py`'s FastAPI metadata and the CLI's `--version` - and all three
# said 0.1.0 while `pyproject.toml` said 0.0.1. Read from the installed
# distribution so there is nothing to keep in step.
__version__ = version("agenticos")
