"""Writes the OpenAPI document to a file so the frontend can generate its types from it.

Usage: ``python -m tutor_calendar.api.export_openapi ../frontend/openapi.json``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tutor_calendar.api.main import create_app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    document = create_app().openapi()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    Path(sys.argv[1]).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
