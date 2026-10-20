"""Fetch the immutable Arduino library used by native send-path regressions."""
import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

URL = "https://downloads.arduino.cc/libraries/github.com/arduino-libraries/ArduinoHttpClient-0.6.1.zip"
SHA256 = "49a6c0f63c8f28f1dacd68a1d569c9a8ddf47a642e4f55fbc941462ad492f7c8"


def sources(cache: Path, destination: Path) -> Path:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError("ArduinoHttpClient archive exceeds size limit")
        if hashlib.sha256(payload).hexdigest() != SHA256:
            raise ValueError("ArduinoHttpClient archive checksum mismatch")
        cache.write_bytes(payload)
    payload = cache.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("ArduinoHttpClient archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            parts = Path(member.filename).parts
            # Copy only flat source files; never extract arbitrary archive paths.
            if len(parts) == 3 and parts[1] == "src" and not member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                (destination / parts[2]).write_bytes(archive.read(member))
    return destination
