from pathlib import PurePosixPath
import re
import zipfile

from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, release_paths, resolve_program_root

ENTRY = "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php"


def plugin_paths():
    root = resolve_program_root()
    archive, source = release_paths(root)
    assert source == root / SOURCE_EXPECTATIONS.source_relative_path
    assert archive == root / SOURCE_EXPECTATIONS.artifact_relative_path
    return root, source, archive


def test_plugin_zip_is_posix_portable_and_fixed_shape() -> None:
    _, _, zip_path = plugin_paths()
    with zipfile.ZipFile(zip_path) as archive:
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
    root, source, zip_path = plugin_paths()
    assert source.parent == root / "wordpress" and zip_path.parent == root / "wordpress" / "dist"
    expected = {f"{source.name}/{path.relative_to(source).as_posix()}": path.read_bytes() for path in source.rglob("*") if path.is_file()}
    with zipfile.ZipFile(zip_path) as archive:
        actual = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    assert actual == expected
