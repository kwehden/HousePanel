"""Compile both reviewed panel identities with dummy credentials; never flash."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="housepanel-firmware-") as directory:
        root = Path(directory)
        sketch = root / "housepanel-giga"
        shutil.copytree(ROOT / "firmware/housepanel-giga", sketch,
                        ignore=shutil.ignore_patterns("secrets.h"))
        shutil.copyfile(sketch / "secrets.h.example", sketch / "secrets.h")
        for panel, hostname in (("primary", "housepanel"), ("panel-2", "housepanel-2")):
            subprocess.run([
                "arduino-cli", "compile", "--fqbn", "arduino:mbed_giga:giga",
                "--build-property",
                f'compiler.cpp.extra_flags=-DHOUSEPANEL_PANEL_ID="{panel}" -DHOUSEPANEL_HOSTNAME="{hostname}"',
                "--build-path", str(root / (panel + "-build")), str(sketch),
            ], check=True)


if __name__ == "__main__":
    main()
