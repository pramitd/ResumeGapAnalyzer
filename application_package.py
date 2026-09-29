from __future__ import annotations

import io
import zipfile
from pathlib import Path


def create_application_zip(app_dir: Path) -> bytes:
    """Return the selected application folder as a downloadable ZIP."""
    app_dir = Path(app_dir).resolve()

    if not app_dir.exists() or not app_dir.is_dir():
        raise FileNotFoundError(f"Application folder not found: {app_dir}")

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as zf:
        for path in sorted(app_dir.rglob("*")):
            if not path.is_file():
                continue

            # Never include Python caches/compiled files.
            if "__pycache__" in path.parts:
                continue
            if path.suffix.lower() in {".pyc", ".pyo"}:
                continue

            archive_name = Path(app_dir.name) / path.relative_to(app_dir)
            zf.write(path, arcname=str(archive_name))

    return buffer.getvalue()
