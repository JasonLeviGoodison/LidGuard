"""Stdlib-only PEP 517 backend for lid-guard.

This project intentionally supports ``pip install --no-build-isolation .`` in
clean Python 3.10+ environments where setuptools is not preinstalled.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = ROOT / "src" / "lidguard"
LICENSE_FILE = ROOT / "LICENSE"

NAME = "lid-guard"
SUMMARY = "Keep your laptop awake on lid close while selected coding agents keep running."
AUTHOR = "Jason Levi Goodison"
PYTHON_REQUIRES = ">=3.10"
KEYWORDS = ["cli", "laptop", "sleep", "agents", "macos", "linux"]
CLASSIFIERS = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: System :: Systems Administration",
    "Topic :: Utilities",
]
PROJECT_URLS = {
    "Homepage": "https://github.com/JasonLeviGoodison/AlwaysGrinding",
    "Repository": "https://github.com/JasonLeviGoodison/AlwaysGrinding",
    "Issues": "https://github.com/JasonLeviGoodison/AlwaysGrinding/issues",
}
ENTRY_POINTS = {
    "console_scripts": {
        "lid-guard": "lidguard.cli:main",
    }
}
MODULE_NAME = "lidguard"
WHEEL_TAG = "py3-none-any"
GENERATOR = "lid-guard stdlib backend"


def _version() -> str:
    init_file = PACKAGE_ROOT / "__init__.py"
    content = init_file.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', content, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"Could not determine version from {init_file}")
    return match.group(1)


def _distribution_name() -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", NAME)


def _dist_info_dir() -> str:
    return f"{_distribution_name()}-{_version()}.dist-info"


def _wheel_name() -> str:
    return f"{_distribution_name()}-{_version()}-{WHEEL_TAG}.whl"


def _metadata_contents() -> bytes:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {NAME}",
        f"Version: {_version()}",
        f"Summary: {SUMMARY}",
        f"Author: {AUTHOR}",
        f"Requires-Python: {PYTHON_REQUIRES}",
        f"Keywords: {','.join(KEYWORDS)}",
        "License: MIT",
    ]
    for label, url in PROJECT_URLS.items():
        lines.append(f"Project-URL: {label}, {url}")
    for classifier in CLASSIFIERS:
        lines.append(f"Classifier: {classifier}")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _wheel_contents() -> bytes:
    content = "\n".join(
        [
            "Wheel-Version: 1.0",
            f"Generator: {GENERATOR}",
            "Root-Is-Purelib: true",
            f"Tag: {WHEEL_TAG}",
            "",
        ]
    )
    return content.encode("utf-8")


def _entry_points_contents() -> bytes:
    lines: list[str] = []
    for group, entries in ENTRY_POINTS.items():
        lines.append(f"[{group}]")
        for name, target in entries.items():
            lines.append(f"{name} = {target}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def _top_level_contents() -> bytes:
    return f"{MODULE_NAME}\n".encode("utf-8")


def _iter_package_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        archive_name = f"{MODULE_NAME}/{path.relative_to(PACKAGE_ROOT).as_posix()}"
        files.append((path, archive_name))
    return files


def _metadata_files() -> dict[str, bytes]:
    dist_info = _dist_info_dir()
    files = {
        f"{dist_info}/METADATA": _metadata_contents(),
        f"{dist_info}/WHEEL": _wheel_contents(),
        f"{dist_info}/entry_points.txt": _entry_points_contents(),
        f"{dist_info}/top_level.txt": _top_level_contents(),
    }
    if LICENSE_FILE.exists():
        files[f"{dist_info}/licenses/LICENSE"] = LICENSE_FILE.read_bytes()
    return files


def _load_prepared_metadata(metadata_directory: str | None) -> dict[str, bytes]:
    if metadata_directory is None:
        return _metadata_files()

    metadata_root = Path(metadata_directory)
    dist_info_dir = metadata_root / _dist_info_dir()
    if not dist_info_dir.exists():
        return _metadata_files()

    files: dict[str, bytes] = {}
    for path in sorted(dist_info_dir.rglob("*")):
        if path.is_file():
            files[path.relative_to(metadata_root).as_posix()] = path.read_bytes()
    return files


def _record_line(path: str, data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{path},sha256={encoded},{len(data)}"


def _record_contents(files: dict[str, bytes], record_path: str) -> bytes:
    rows = [_record_line(path, data) for path, data in sorted(files.items())]
    rows.append(f"{record_path},,")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(row.split(",", 2))
    return buffer.getvalue().encode("utf-8")


def _write_metadata_directory(target_root: Path) -> str:
    dist_info = target_root / _dist_info_dir()
    dist_info.mkdir(parents=True, exist_ok=True)
    for relative_path, data in _metadata_files().items():
        path = target_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return dist_info.name


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings=None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings=None) -> str:
    return _write_metadata_directory(Path(metadata_directory))


def build_wheel(
    wheel_directory: str, config_settings=None, metadata_directory: str | None = None
) -> str:
    wheel_dir = Path(wheel_directory)
    wheel_dir.mkdir(parents=True, exist_ok=True)

    dist_info = _dist_info_dir()
    files: dict[str, bytes] = {}
    for source_path, archive_name in _iter_package_files():
        files[archive_name] = source_path.read_bytes()
    files.update(_load_prepared_metadata(metadata_directory))

    record_path = f"{dist_info}/RECORD"
    files[record_path] = _record_contents(files, record_path)

    wheel_path = wheel_dir / _wheel_name()
    with zipfile.ZipFile(
        wheel_path, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for archive_name, data in sorted(files.items()):
            archive.writestr(archive_name, data)

    return wheel_path.name


def build_sdist(sdist_directory: str, config_settings=None) -> str:
    sdist_dir = Path(sdist_directory)
    sdist_dir.mkdir(parents=True, exist_ok=True)

    sdist_name = f"{_distribution_name()}-{_version()}.tar.gz"
    sdist_path = sdist_dir / sdist_name
    prefix = f"{_distribution_name()}-{_version()}"

    with tarfile.open(sdist_path, mode="w:gz") as archive:
        for relative_path in ["pyproject.toml", "README.md", "LICENSE", "build_backend.py"]:
            path = ROOT / relative_path
            if path.exists():
                archive.add(path, arcname=f"{prefix}/{relative_path}")
        for source_path, archive_name in _iter_package_files():
            archive.add(source_path, arcname=f"{prefix}/src/{archive_name}")

    return sdist_path.name
