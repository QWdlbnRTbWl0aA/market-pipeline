"""Public entry point enforces saved-artifact intake and credential separation."""
from .services import main

if __name__ == '__main__':
    raise SystemExit(main())
