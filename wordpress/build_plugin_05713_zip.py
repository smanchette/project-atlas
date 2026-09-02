from __future__ import annotations

from pathlib import Path, PurePosixPath
import zipfile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "project-atlas-metadata-bridge-0.57.13"
OUTPUT = ROOT / "dist" / "project-atlas-metadata-bridge-0.57.13.zip"
ARCHIVE_ROOT = "project-atlas-metadata-bridge"
FIXED_TIMESTAMP = (2026, 9, 2, 0, 0, 0)
EXPECTED_FILES = (
    "README.md",
    "assets/performance-local-v5.css",
    "assets/performance-local-v5.js",
    "includes/performance-local-v5-form-delivery.php",
    "includes/performance-local-v5-page-payload.php",
    "includes/performance-local-v5-renderer.php",
    "project-atlas-metadata-bridge.php",
    "templates/performance-local-v5-page.php",
)


def _source_files() -> list[tuple[str, Path]]:
    if SOURCE.is_symlink() or not SOURCE.is_dir():
        raise RuntimeError(f"Plugin source root is absent, invalid, or symbolic: {SOURCE}")

    source_root = SOURCE.resolve(strict=True)
    discovered: dict[str, Path] = {}
    for path in SOURCE.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Symbolic links are forbidden in plugin source: {path}")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError(f"Plugin source path escapes its root: {path}") from exc
        if not path.is_file():
            continue
        relative = path.relative_to(SOURCE).as_posix()
        if relative in discovered:
            raise RuntimeError(f"Duplicate plugin source path: {relative}")
        discovered[relative] = path

    expected = set(EXPECTED_FILES)
    actual = set(discovered)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise RuntimeError(
            f"Plugin source inventory differs; missing={missing}, unexpected={unexpected}"
        )

    return [(relative, discovered[relative]) for relative in sorted(EXPECTED_FILES)]


def build() -> Path:
    files = _source_files()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        OUTPUT,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.comment = b""
        for relative, source in files:
            archive_path = PurePosixPath(ARCHIVE_ROOT, *PurePosixPath(relative).parts)
            info = zipfile.ZipInfo(str(archive_path), date_time=FIXED_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)
    return OUTPUT


if __name__ == "__main__":
    print(build())
