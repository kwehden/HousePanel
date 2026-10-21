"""Private, identity-bound GIGA build/bootstrap and encrypted LAN OTA upload.

Never called by backend CD. Firmware embeds network credentials; keep artifacts
and per-panel keys local. Requires cryptography for the OTA encryption primitive.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import tarfile
import tempfile
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
PANELS = {"primary": (1, "housepanel"), "panel-2": (2, "housepanel-2")}
PORT = 8266
MAX_IMAGE = 0x08180000 - 0x08040000


def identity(panel: str) -> bytes:
    return f"HousePanel identity:{panel}:{PANELS[panel][1]}:end".encode("ascii")


def key(path: Path) -> bytes:
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Key must be a private regular file (mode 0600 or 0400)")
    value = path.read_bytes()
    if len(value) != 32 or not any(value):
        raise ValueError("Key must contain exactly 32 random binary bytes")
    return value


def derive(secret: bytes, label: bytes) -> bytes:
    return hmac.digest(secret, label, "sha256")


def auth_key(secret: bytes) -> bytes:
    return derive(secret, b"housepanel-ota-authentication-v1")


def envelope(panel: str, challenge: str, image: bytes, secret: bytes) -> tuple[bytes, bytes]:
    if not re.fullmatch(r"[0-9a-f]{64}", challenge):
        raise ValueError("Invalid board challenge")
    if not 256 <= len(image) <= MAX_IMAGE or identity(panel) not in image:
        raise ValueError("Invalid image size or wrong embedded panel identity")
    stack, reset = struct.unpack("<II", image[:8])
    if not 0x24000000 < stack <= 0x24080000 or stack & 7 or not reset & 1 or not 0x08040000 <= reset < 0x08040000 + len(image):
        raise ValueError("Image is not a supported GIGA M7 application binary")
    nonce = bytes.fromhex(challenge)
    encryptor = Cipher(algorithms.AES(derive(secret, b"housepanel-ota-encryption-v1")), modes.CTR(nonce[:16])).encryptor()
    wire = encryptor.update(image) + encryptor.finalize()
    header = (b"HPOTA1U\n" + bytes([PANELS[panel][0]]) + struct.pack(">I", len(image)) + nonce +
              hashlib.sha256(image).digest() + hashlib.sha256(wire).digest())
    return header + hmac.digest(auth_key(secret), header, "sha256"), wire


def read_line(stream, maximum: int) -> bytes:
    value = stream.readline(maximum + 1)
    if not value.endswith(b"\n") or len(value) > maximum:
        raise ValueError("Oversized or incomplete updater response")
    return value


def status(host: str, secret: bytes, *, port: int = PORT) -> dict:
    request_nonce = os.urandom(32)
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall(b"HPOTA1S\n" + request_nonce)
        with connection.makefile("rb") as stream:
            body = read_line(stream, 512)
            tag = read_line(stream, 65).strip()
    expected = hmac.digest(auth_key(secret), body, "sha256").hex().encode("ascii")
    if not hmac.compare_digest(expected, tag):
        raise ValueError("Board status authentication failed")
    value = json.loads(body)
    if not isinstance(value, dict) or value.get("protocol") != 1:
        raise ValueError("Unsupported updater protocol")
    if value.get("request_nonce") != request_nonce.hex():
        raise ValueError("Replayed board status response")
    return value


def verify_identity(value: dict, panel: str) -> None:
    if (value.get("panel_id") != panel or value.get("hostname") != PANELS[panel][1] or
            value.get("identity") != identity(panel).decode("ascii")):
        raise ValueError("Board identity does not match the requested panel")


def load_image(panel: str, manifest_path: Path) -> tuple[dict, Path, bytes]:
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("panel_id") != panel or manifest.get("hostname") != PANELS[panel][1] or
            not re.fullmatch(r"[0-9a-f]{40}", manifest.get("revision", ""))):
        raise ValueError("Manifest identity or Git revision mismatch")
    name = manifest.get("image", "")
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".bin"):
        raise ValueError("Manifest image must be a sibling .bin file")
    binary = manifest_path.parent / name
    if not 256 <= binary.stat().st_size <= MAX_IMAGE:
        raise ValueError("Invalid firmware size")
    image = binary.read_bytes()
    if hashlib.sha256(image).hexdigest() != manifest.get("sha256") or len(image) != manifest.get("size"):
        raise ValueError("Firmware does not match its build manifest")
    if identity(panel) not in image or manifest["revision"].encode("ascii") not in image:
        raise ValueError("Compiled image does not contain its declared identity/revision")
    return manifest, binary, image


def upload(host: str, panel: str, manifest_path: Path, secret: bytes, *, port: int = PORT) -> dict:
    manifest, _, image = load_image(panel, manifest_path)
    if manifest.get("ota_key_sha256") != hashlib.sha256(secret).hexdigest():
        raise ValueError("Firmware was built with a different OTA key; routine upload cannot rotate keys")
    before = status(host, secret, port=port)
    verify_identity(before, panel)
    if before.get("ready") is not True or not re.fullmatch(r"[0-9a-f]{32}", before.get("boot_id", "")):
        raise ValueError("Updater is not ready")
    header, ciphertext = envelope(panel, before["challenge"], image, secret)
    with socket.create_connection((host, port), timeout=30) as connection:
        connection.sendall(header)
        with connection.makefile("rb") as stream:
            if json.loads(read_line(stream, 128)).get("accepted") is not True:
                raise ValueError("Panel rejected update authorization")
            connection.sendall(ciphertext)
            try:
                acknowledgement = json.loads(read_line(stream, 128))
            except (OSError, ValueError):
                # A reboot can race delivery of the final reply. Never resend
                # the image automatically; reconcile using signed boot/revision.
                acknowledgement = None
            if acknowledgement is not None and (not isinstance(acknowledgement, dict) or acknowledgement.get("ok") is not True):
                raise ValueError("Panel rejected staged firmware")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            after = status(host, secret, port=port)
        except (OSError, ValueError):
            continue
        verify_identity(after, panel)
        if (after.get("revision") == manifest["revision"] and after.get("boot_id") != before["boot_id"] and
                after.get("ready") is True):
            return after
    raise TimeoutError("Update result uncertain: no authenticated new-boot/revision confirmation; inspect before retrying")


def bootstrap(panel: str, manifest_path: Path, serial: str) -> None:
    """One-time serial-identity checked upload; never format QSPI or flash a bootloader."""
    _, binary, _ = load_image(panel, manifest_path)
    inventory = json.loads(subprocess.check_output(["arduino-cli", "board", "list", "--format", "json"], text=True))
    matches = []
    for detected in inventory.get("detected_ports", []):
        port = detected.get("port", {})
        if (port.get("protocol") == "serial" and port.get("properties", {}).get("serialNumber") == serial and
                any(board.get("fqbn") == "arduino:mbed_giga:giga" for board in detected.get("matching_boards", []))):
            matches.append(port["address"])
    if len(matches) != 1:
        raise ValueError("Exactly one USB GIGA with the specified hardware serial is required; no upload attempted")
    subprocess.run(["arduino-cli", "upload", "--fqbn", "arduino:mbed_giga:giga", "--port", matches[0],
                    "--input-file", str(binary.resolve()), "--verify"], check=True)


def build(panel: str, revision: str, key_file: Path, output: Path) -> Path:
    resolved = subprocess.check_output(["git", "rev-parse", f"{revision}^{{commit}}"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise ValueError("Invalid Git revision")
    secret = key(key_file)
    if output.exists():
        raise ValueError("Output directory already exists; preserve previous firmware evidence")
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    with tempfile.TemporaryDirectory(prefix="housepanel-private-firmware-") as directory:
        temporary = Path(directory)
        archive = subprocess.check_output(["git", "archive", resolved, "firmware/housepanel-giga"], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(temporary, filter="data")
        sketch = temporary / "firmware/housepanel-giga"
        # Credentials never enter Git, argv, CI artifacts, or a public update server.
        (sketch / "secrets.h").write_bytes((ROOT / "firmware/housepanel-giga/secrets.h").read_bytes())
        (sketch / "ota_secrets.h").write_text(f'#pragma once\n#define HOUSEPANEL_OTA_KEY_HEX "{secret.hex()}"\n')
        common = f'-DLV_CONF_PATH="{sketch / "housepanel_lv_conf.h"}" -DWS_TX_BUFFER_SIZE=768'
        subprocess.run([
            "arduino-cli", "compile", "--fqbn", "arduino:mbed_giga:giga",
            "--build-property", f'compiler.cpp.extra_flags=-DHOUSEPANEL_PANEL_ID="{panel}" '
            f'-DHOUSEPANEL_HOSTNAME="{PANELS[panel][1]}" -DHOUSEPANEL_FIRMWARE_REVISION="{resolved}" {common}',
            "--build-property", f"compiler.c.extra_flags={common}",
            "--build-path", str(temporary / "objects"), "--output-dir", str(output.resolve()), str(sketch),
        ], check=True)
    binary = output / "housepanel-giga.ino.bin"
    data = binary.read_bytes()
    if identity(panel) not in data:
        raise ValueError("Compiled firmware has no matching OTA identity")
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"panel_id": panel, "hostname": PANELS[panel][1], "revision": resolved,
                                    "ota_key_sha256": hashlib.sha256(secret).hexdigest(),
                                    "image": binary.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("keygen", help="Generate a new private per-panel key; never overwrite")
    generate.add_argument("path", type=Path)
    compile_command = sub.add_parser("build", help="Compile an exact committed revision with private credentials")
    compile_command.add_argument("--revision", required=True)
    compile_command.add_argument("--output", type=Path, required=True)
    bootstrap_command = sub.add_parser("bootstrap", help="One-time USB install, guarded by GIGA hardware serial")
    bootstrap_command.add_argument("--panel", choices=PANELS, required=True)
    bootstrap_command.add_argument("--manifest", type=Path, required=True)
    bootstrap_command.add_argument("--serial", required=True)
    for name in ("status", "upload"):
        operation = sub.add_parser(name)
        operation.add_argument("--host", required=True)
        if name == "upload":
            operation.add_argument("--manifest", type=Path, required=True)
    for operation in (compile_command, sub.choices["status"], sub.choices["upload"]):
        operation.add_argument("--panel", choices=PANELS, required=True)
        operation.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "keygen":
        args.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(os.urandom(32))
    elif args.command == "build":
        print(build(args.panel, args.revision, args.key_file, args.output))
    elif args.command == "bootstrap":
        bootstrap(args.panel, args.manifest, args.serial)
    elif args.command == "status":
        value = status(args.host, key(args.key_file))
        verify_identity(value, args.panel)
        print(json.dumps(value, indent=2))
    else:
        print(json.dumps(upload(args.host, args.panel, args.manifest, key(args.key_file)), indent=2))


if __name__ == "__main__":
    main()
