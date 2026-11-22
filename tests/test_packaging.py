"""The Flatpak packaging files agree with each other and with the application."""

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from leitorpdf.app import APP_ID

PACKAGING = Path(__file__).parent.parent / "packaging" / "flatpak"


def packaged(suffix):
    return PACKAGING / f"{APP_ID}{suffix}"


def manifest():
    return json.loads(packaged(".json").read_text(encoding="utf-8"))


def test_manifest_describes_this_app():
    data = manifest()
    assert data["id"] == APP_ID
    assert data["command"] == "leitorpdf"
    assert data["runtime"] == "org.freedesktop.Platform"
    assert data["sdk"] == "org.freedesktop.Sdk"
    assert data["runtime-version"] == "26.08"  # has Python 3.14 and ffmpeg with MP3
    for permission in (
        "--socket=wayland",
        "--socket=fallback-x11",
        "--socket=pulseaudio",  # reading aloud
        "--share=network",  # voices and OCR data are downloaded on demand
        "--filesystem=home",  # open PDFs, save MP3s, drag and drop
    ):
        assert permission in data["finish-args"]
    assert [module["name"] for module in data["modules"]] == ["python-deps", "krb5", "leitorpdf"]


def test_kerberos_library_is_bundled_from_a_pinned_source():
    # Qt's network and multimedia libraries in the PySide6 wheels load
    # libgssapi_krb5, which the freedesktop runtime does not ship.
    [krb5] = [module for module in manifest()["modules"] if module["name"] == "krb5"]
    [source] = krb5["sources"]
    assert source["url"].startswith("https://kerberos.org/dist/krb5/")
    assert len(source["sha256"]) == 64


def test_requirements_pin_what_the_app_was_tested_with():
    lines = [
        line.strip()
        for line in (PACKAGING / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert all("==" in line for line in lines)
    names = {line.split("==")[0].lower() for line in lines}
    assert {"pyside6-essentials", "pyside6-addons", "piper-tts", "onnxruntime", "numpy"} <= names
    assert "pymupdf" not in names  # installed apart, without its optional extras
    assert (PACKAGING / "requirements-nodeps.txt").read_text().strip().lower().startswith("pymupdf==")


def test_desktop_file():
    text = packaged(".desktop").read_text(encoding="utf-8")
    entries = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert entries["Type"] == "Application"
    assert entries["Name"] == "LeitorPDF"
    assert entries["Exec"] == "leitorpdf %f"
    assert entries["Icon"] == APP_ID
    assert "application/pdf" in entries["MimeType"].split(";")
    assert entries["Terminal"] == "false"
    assert "voz alta" in entries["Comment"]
    if shutil.which("desktop-file-validate"):
        result = subprocess.run(
            ["desktop-file-validate", str(packaged(".desktop"))], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_metainfo():
    root = ET.parse(packaged(".metainfo.xml")).getroot()
    assert root.findtext("id") == APP_ID
    assert root.findtext("name") == "LeitorPDF"
    assert root.findtext("project_license") == "AGPL-3.0-or-later"
    assert root.find("launchable").text == f"{APP_ID}.desktop"
    assert root.find("releases/release").get("version") == "0.1.0"
    if shutil.which("appstreamcli"):
        result = subprocess.run(
            ["appstreamcli", "validate", "--no-net", str(packaged(".metainfo.xml"))],
            capture_output=True, text=True,
        )  # fmt: skip
        problems = [line for line in result.stdout.splitlines() if line.startswith(("E:", "W:"))]
        # The project has no website yet; that is the one accepted complaint.
        assert [p for p in problems if "url-homepage-missing" not in p] == [], result.stdout


def test_icon_is_an_svg():
    root = ET.parse(packaged(".svg")).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_build_script_is_runnable():
    script = PACKAGING / "build.sh"
    assert os.access(script, os.X_OK)
    text = script.read_text()
    assert APP_ID in text and "flatpak build-bundle" in text
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_version_is_the_same_everywhere():
    import tomllib

    import leitorpdf

    project = tomllib.loads((PACKAGING.parent.parent / "pyproject.toml").read_text())
    assert project["project"]["version"] == leitorpdf.__version__ == "0.1.0"
