"""Compile full-panel identities and the simplified primary; never flash."""
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
                        ignore=shutil.ignore_patterns("secrets.h", "ota_secrets.h"))
        shutil.copyfile(sketch / "secrets.h.example", sketch / "secrets.h")
        lv_config = f'-DLV_CONF_PATH="{sketch / "housepanel_lv_conf.h"}" -DWS_TX_BUFFER_SIZE=768'
        for panel, hostname in (("primary", "housepanel"), ("panel-2", "housepanel-2")):
            subprocess.run([
                "arduino-cli", "compile", "--fqbn", "arduino:mbed_giga:giga",
                "--build-property",
                f'compiler.cpp.extra_flags=-DHOUSEPANEL_PANEL_ID="{panel}" -DHOUSEPANEL_HOSTNAME="{hostname}" {lv_config}',
                "--build-property", f"compiler.c.extra_flags={lv_config}",
                "--build-path", str(root / (panel + "-build")), str(sketch),
            ], check=True)

        simplified = root / "giga-filament"
        shutil.copytree(ROOT / "firmware/giga-filament", simplified,
                        ignore=shutil.ignore_patterns("secrets.h"))
        shutil.copyfile(simplified / "secrets.h.example", simplified / "secrets.h")
        subprocess.run([
            "arduino-cli", "compile", "--fqbn", "arduino:mbed_giga:giga",
            "--build-path", str(root / "simplified-primary-build"), str(simplified),
        ], check=True)


if __name__ == "__main__":
    main()
