"""Export only HTTP schemas: never open a book library or start intake work."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from book_library.web import create_app


def main() -> None:
    app = create_app(object(), enable_intake_worker=False)
    destination = ROOT / "frontend" / "openapi.json"
    schema = app.openapi()
    # Pydantic validates JsonValue recursively but emits an unconstrained schema.
    # Describe that recursive JSON contract explicitly for TypeScript consumers.
    schema["components"]["schemas"]["JsonValue"] = {
        "anyOf": [
            {"type": "null"}, {"type": "boolean"}, {"type": "number"}, {"type": "string"},
            {"type": "array", "items": {"$ref": "#/components/schemas/JsonValue"}},
            {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/JsonValue"}},
        ]
    }
    destination.write_text(json.dumps(schema, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
