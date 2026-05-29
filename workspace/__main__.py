"""Enable `python -m workspace` (or `python __main__.py`) as a convenience alias for the Synapse CLI."""

from synapse_cli import app

if __name__ == "__main__" and getattr(__spec__, "name", None) != "__main__":
    app()
