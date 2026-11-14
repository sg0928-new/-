"""PyInstaller entry script: `python launch.py` behaves exactly like `python -m privacyguard`."""

from privacyguard.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
