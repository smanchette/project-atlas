from __future__ import annotations

from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "project-atlas-upgrade-bootstrap-0.2.0"
OUTPUT = ROOT / "dist" / "project-atlas-upgrade-bootstrap-0.2.0.zip"
ARCHIVE_ROOT = "project-atlas-upgrade-bootstrap"

def build() -> Path:
    files = sorted(path for path in SOURCE.rglob("*") if path.is_file())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            relative = PurePosixPath(ARCHIVE_ROOT, *source.relative_to(SOURCE).parts)
            info = zipfile.ZipInfo(str(relative), date_time=(2026, 7, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)
    return OUTPUT

if __name__ == "__main__":
    print(build())
