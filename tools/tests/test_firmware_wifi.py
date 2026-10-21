"""Execute the actual startup manager against synchronous Wi-Fi failures."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=["primary", "panel-2"])
def startup_binary(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("wifi-startup")
    source = ROOT / "firmware/housepanel-giga"
    for name in ("wifi_manager.cpp", "wifi_manager.h", "config.h"):
        shutil.copyfile(source / name, directory / name)
    shutil.copyfile(source / "secrets.h.example", directory / "secrets.h")
    fixtures = ROOT / "tools/tests/firmware"
    hostname = "housepanel" if request.param == "primary" else "housepanel-2"
    binary = directory / "startup"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=all",
        "-I", str(fixtures / "wifi"), "-I", str(fixtures / "arduino"),
        "-I", str(directory), f'-DHOUSEPANEL_HOSTNAME="{hostname}"',
        str(directory / "wifi_manager.cpp"), str(fixtures / "wifi/startup_test.cpp"),
        "-o", str(binary),
    ], check=True)
    return binary


@pytest.mark.parametrize("failures,mode", [(0, 0), (1, 0), (30, 0), (2, 1), (0, 2)])
def test_startup_retries_with_cleanup_serviced_backoff_and_preserved_identity(startup_binary, failures, mode):
    subprocess.run([startup_binary, str(failures), str(mode)], check=True, timeout=5)
