from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "wordpress" / "project-atlas-metadata-bridge"
ZIP = ROOT / "wordpress" / "dist" / "project-atlas-metadata-bridge-0.57.4.zip"
ENTRY = "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php"


def test_plugin_zip_is_posix_portable_and_fixed_shape() -> None:
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        assert names and len(names) == len(set(names))
        assert names.count(ENTRY) == 1
        assert all("\\" not in name for name in names)
        assert all(not name.startswith(("/", "\\")) for name in names)
        assert all(not re.match(r"^[A-Za-z]:", name) for name in names)
        assert all(".." not in PurePosixPath(name).parts for name in names)
        assert {PurePosixPath(name).parts[0] for name in names} == {"project-atlas-metadata-bridge"}
        assert not any(re.fullmatch(r"project-atlas-metadata-bridge-\d[^/]*", PurePosixPath(name).parts[0]) for name in names)
        php = archive.read(ENTRY)
        assert php.startswith(b"<?php") and len(php) > 100


def test_plugin_zip_matches_source_byte_for_byte() -> None:
    expected = {f"{SOURCE.name}/{path.relative_to(SOURCE).as_posix()}": path.read_bytes() for path in SOURCE.rglob("*") if path.is_file()}
    with zipfile.ZipFile(ZIP) as archive:
        actual = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    assert actual == expected
