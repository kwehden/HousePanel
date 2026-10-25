"""Stage the canonical OTA receiver beside an interface's sketch sources."""
from pathlib import Path
import shutil

OTA_SOURCES = ("ota_update.cpp", "ota_update.h", "ota_protocol.cpp", "ota_protocol.h")


def stage_ota(root: Path, sketch: Path) -> None:
    for name in OTA_SOURCES:
        shutil.copyfile(root / "firmware/housepanel-giga" / name, sketch / name)
