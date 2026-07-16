from __future__ import annotations

from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "project-atlas-upgrade-bootstrap"
OUTPUT = ROOT / "dist" / "project-atlas-upgrade-bootstrap-0.1.0.zip"


def main() -> None:
    files = sorted(path for path in SOURCE.rglob("*") if path.is_file())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(ROOT)
            info = zipfile.ZipInfo(str(relative).replace("\\", "/"), date_time=(2026, 7, 16, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


if __name__ == "__main__":
    main()
