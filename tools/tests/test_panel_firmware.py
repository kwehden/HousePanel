"""Cross-language OTA authentication, encryption, ownership and host acceptance."""
import hashlib
import hmac
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import panel_firmware as ota

KEY = bytes(range(1, 33))
CHALLENGE = bytes(range(32)).hex()
IMAGE = struct.pack("<II", 0x24080000, 0x08040021) + b"\0" * 245 + ota.identity("primary") + b"a" * 40 + b"private credentials" * 80


@pytest.fixture(scope="module")
def protocol(tmp_path_factory):
    path = tmp_path_factory.mktemp("ota-native")
    for name in ("aes", "md", "sha256"):
        header = path / "mbedtls" / f"{name}.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text('#include "ota_crypto.h"\n')
    fixtures = ROOT / "tools/tests/firmware"
    firmware = ROOT / "firmware/housepanel-giga"
    binary = path / "receiver"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations",
        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(path), "-I", str(fixtures),
        "-I", str(firmware), str(fixtures / "ota_protocol_test.cpp"), str(firmware / "ota_protocol.cpp"),
        "-lcrypto", "-o", str(binary),
    ], check=True)
    return binary


def invoke(protocol, tmp_path, header, wire, mode="ok", secret=KEY, panel="primary"):
    payload = tmp_path / "wire"
    output = tmp_path / "plain"
    payload.write_bytes(header + wire)
    subprocess.run([protocol, payload, secret.hex(), output, mode, panel], check=True)
    return output


@pytest.mark.parametrize("panel", ota.PANELS)
def test_actual_receiver_decrypts_identity_bound_host_image(protocol, tmp_path, panel):
    image = IMAGE.replace(ota.identity("primary"), ota.identity(panel))
    header, wire = ota.envelope(panel, CHALLENGE, image, KEY)
    assert len(header) == 141 and image not in wire
    assert b"private credentials" not in wire
    output = invoke(protocol, tmp_path, header, wire, panel=panel)
    assert output.read_bytes() == image


@pytest.mark.parametrize("offset", [0, 8, 9, 13, 45, 77, 109, 140])
def test_header_tampering_never_opens_storage(protocol, tmp_path, offset):
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, KEY)
    header = bytearray(header)
    header[offset] ^= 1
    invoke(protocol, tmp_path, header, wire, "header_reject")


def test_wrong_panel_and_key_never_open_storage(protocol, tmp_path):
    header, wire = ota.envelope("panel-2", CHALLENGE, IMAGE.replace(ota.identity("primary"), ota.identity("panel-2")), KEY)
    invoke(protocol, tmp_path, header, wire, "header_reject")
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, b"x" * 32)
    invoke(protocol, tmp_path, header, wire, "header_reject")


@pytest.mark.parametrize("mode", ["begin_failure", "write_failure", "finish_failure", "cancel", "oversize"])
def test_error_and_cancellation_cleanup_and_replay_rejection(protocol, tmp_path, mode):
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, KEY)
    invoke(protocol, tmp_path, header, wire, mode)


def test_tampered_ciphertext_never_finishes(protocol, tmp_path):
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, KEY)
    wire = bytearray(wire)
    wire[-1] ^= 1
    invoke(protocol, tmp_path, header, wire, "body_reject")


def test_even_authorized_wrong_identity_cannot_finish(protocol, tmp_path):
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, KEY)
    # Simulate a buggy/compromised packager that signs a peer's image as primary.
    other = IMAGE.replace(ota.identity("primary"), b"x" * len(ota.identity("primary")))
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    encryptor = Cipher(algorithms.AES(ota.derive(KEY, b"housepanel-ota-encryption-v1")), modes.CTR(bytes.fromhex(CHALLENGE)[:16])).encryptor()
    wire = encryptor.update(other) + encryptor.finalize()
    unsigned = header[:45] + hashlib.sha256(other).digest() + hashlib.sha256(wire).digest()
    header = unsigned + hmac.digest(ota.auth_key(KEY), unsigned, "sha256")
    invoke(protocol, tmp_path, header, wire, "body_reject")


@pytest.mark.parametrize("size", [0, 255, ota.MAX_IMAGE + 1, 2**32 - 1])
def test_authenticated_invalid_size_never_opens_storage(protocol, tmp_path, size):
    header, wire = ota.envelope("primary", CHALLENGE, IMAGE, KEY)
    unsigned = header[:9] + struct.pack(">I", size) + header[13:109]
    header = unsigned + hmac.digest(ota.auth_key(KEY), unsigned, "sha256")
    invoke(protocol, tmp_path, header, wire, "header_reject")


def test_private_key_permissions_and_dummy_rejected(tmp_path):
    path = tmp_path / "key"
    path.write_bytes(KEY)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        ota.key(path)
    path.chmod(0o600)
    assert ota.key(path) == KEY
    path.write_bytes(bytes(32))
    with pytest.raises(ValueError, match="random"):
        ota.key(path)


@pytest.mark.parametrize("tag_valid", [True, False])
def test_real_socket_status_authentication(tag_valid):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    errors = []

    def board():
        try:
            with listener, listener.accept()[0] as connection:
                with connection.makefile("rb") as stream:
                    request = stream.read(40)
                assert request[:8] == b"HPOTA1S\n" and len(request) == 40
                body = json.dumps({"protocol": 1, "ready": True, "request_nonce": request[8:].hex()}).encode() + b"\n"
                tag = hmac.digest(ota.auth_key(KEY if tag_valid else b"z" * 32), body, "sha256").hex().encode()
                connection.sendall(body + tag + b"\n")
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=board)
    worker.start()
    try:
        if tag_valid:
            assert ota.status("127.0.0.1", KEY, port=port)["ready"] is True
        else:
            with pytest.raises(ValueError, match="authentication"):
                ota.status("127.0.0.1", KEY, port=port)
    finally:
        worker.join(timeout=10)
    assert not worker.is_alive() and not errors


def test_manifest_corruption_rejected_before_network(tmp_path, monkeypatch):
    binary = tmp_path / "panel.bin"
    binary.write_bytes(IMAGE)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"panel_id": "primary", "hostname": "housepanel", "revision": "a" * 40,
                                    "image": binary.name, "size": len(IMAGE), "sha256": "0" * 64}))
    monkeypatch.setattr(ota, "status", lambda *args, **kwargs: pytest.fail("must not contact hardware"))
    with pytest.raises(ValueError, match="manifest"):
        ota.upload("unused", "primary", manifest, KEY)


def manifest(tmp_path, image=IMAGE):
    binary = tmp_path / "panel.bin"
    binary.write_bytes(image)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"panel_id": "primary", "hostname": "housepanel", "revision": "a" * 40,
                               "ota_key_sha256": hashlib.sha256(KEY).hexdigest(),
                               "image": binary.name, "size": len(image), "sha256": hashlib.sha256(image).hexdigest()}))
    return path


@pytest.mark.parametrize("kind", ["uno", "wrong_serial", "ambiguous", "giga"])
def test_bootstrap_refuses_other_hardware_and_uses_exact_verified_binary(tmp_path, monkeypatch, kind):
    path = manifest(tmp_path)
    detected = {"matching_boards": [{"fqbn": "arduino:mbed_giga:giga" if kind != "uno" else "arduino:renesas_uno:unor4wifi"}],
                "port": {"address": "/dev/ttyACM7", "protocol": "serial", "properties": {"serialNumber": "other" if kind == "wrong_serial" else "giga-serial"}}}
    inventory = {"detected_ports": [detected] * (2 if kind == "ambiguous" else 1)}
    monkeypatch.setattr(ota.subprocess, "check_output", lambda *args, **kwargs: json.dumps(inventory))
    calls = []
    monkeypatch.setattr(ota.subprocess, "run", lambda *args, **kwargs: calls.append(args[0]))
    if kind == "giga":
        ota.bootstrap("primary", path, "giga-serial")
        assert calls == [["arduino-cli", "upload", "--fqbn", "arduino:mbed_giga:giga", "--port", "/dev/ttyACM7",
                          "--input-file", str(tmp_path / "panel.bin"), "--verify"]]
    else:
        with pytest.raises(ValueError, match="Exactly one"):
            ota.bootstrap("primary", path, "giga-serial")
        assert not calls


def test_host_upload_requires_authenticated_new_boot_and_revision(tmp_path, protocol, monkeypatch):
    path = manifest(tmp_path)
    listener = socket.socket()
    listener.settimeout(5)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    errors = []

    def signed_status(connection, stream, boot, revision):
        request = stream.read(40)
        assert request[:8] == b"HPOTA1S\n"
        body = json.dumps({"protocol": 1, "panel_id": "primary", "hostname": "housepanel",
                           "identity": ota.identity("primary").decode(), "boot_id": boot * 32,
                           "ready": True, "revision": revision, "challenge": CHALLENGE,
                           "request_nonce": request[8:].hex()}, separators=(",", ":")).encode() + b"\n"
        tag = hmac.digest(ota.auth_key(KEY), body, "sha256").hex().encode()
        connection.sendall(body + tag + b"\n")

    def board():
        try:
            with listener:
                with listener.accept()[0] as connection, connection.makefile("rb") as stream:
                    signed_status(connection, stream, "1", "b" * 40)
                with listener.accept()[0] as connection, connection.makefile("rb") as stream:
                    header = stream.read(141)
                    connection.sendall(b'{"accepted":true}\n')
                    wire = stream.read(len(IMAGE))
                    # Feed the real host upload through the actual C++ receiver.
                    assert invoke(protocol, tmp_path, header, wire).read_bytes() == IMAGE
                    connection.sendall(b'{"ok":true}\n')
                with listener.accept()[0] as connection, connection.makefile("rb") as stream:
                    signed_status(connection, stream, "2", "a" * 40)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=board)
    worker.start()
    monkeypatch.setattr(ota.time, "sleep", lambda _: None)
    try:
        result = ota.upload("127.0.0.1", "primary", path, KEY, port=port)
        assert result["boot_id"] == "2" * 32 and result["revision"] == "a" * 40
    finally:
        worker.join(timeout=10)
        listener.close()
    assert not worker.is_alive() and not errors


def test_private_builder_uses_only_committed_source_and_keeps_keys_out_of_argv(tmp_path, monkeypatch):
    import io
    import tarfile
    root = tmp_path / "repo"
    sketch = root / "firmware/housepanel-giga"
    sketch.mkdir(parents=True)
    (sketch / "secrets.h").write_text("PRIVATE WIFI")
    key_path = tmp_path / "key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        info = tarfile.TarInfo("firmware/housepanel-giga/housepanel-giga.ino")
        info.size = len(b"COMMITTED SOURCE")
        bundle.addfile(info, io.BytesIO(b"COMMITTED SOURCE"))

    def output(command, **kwargs):
        assert kwargs["cwd"] == root
        return "a" * 40 if command[1] == "rev-parse" else archive.getvalue()

    def compile_firmware(command, *, check):
        assert check and command[:2] == ["arduino-cli", "compile"]
        copied = Path(command[-1])
        assert (copied / "housepanel-giga.ino").read_text() == "COMMITTED SOURCE"
        assert (copied / "secrets.h").read_text() == "PRIVATE WIFI"
        assert KEY.hex() in (copied / "ota_secrets.h").read_text()
        assert not any(KEY.hex() in argument or "PRIVATE WIFI" in argument for argument in command)
        directory = Path(command[command.index("--output-dir") + 1])
        (directory / "housepanel-giga.ino.bin").write_bytes(IMAGE)

    monkeypatch.setattr(ota, "ROOT", root)
    monkeypatch.setattr(ota.subprocess, "check_output", output)
    monkeypatch.setattr(ota.subprocess, "run", compile_firmware)
    directory = tmp_path / "release"
    result = ota.build("primary", "a" * 40, key_path, directory)
    assert json.loads(result.read_text())["sha256"] == hashlib.sha256(IMAGE).hexdigest()
    assert directory.stat().st_mode & 0o077 == 0
    assert not (sketch / "ota_secrets.h").exists()
    with pytest.raises(ValueError, match="already exists"):
        ota.build("primary", "a" * 40, key_path, directory)


@pytest.fixture(scope="module", params=ota.PANELS)
def runtime(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("ota-runtime")
    sketch = directory / "sketch"
    sketch.mkdir()
    import shutil
    firmware = ROOT / "firmware/housepanel-giga"
    for name in ("ota_update.cpp", "ota_update.h", "ota_protocol.cpp", "ota_protocol.h", "config.h"):
        shutil.copyfile(firmware / name, sketch / name)
    shutil.copyfile(firmware / "secrets.h.example", sketch / "secrets.h")
    (sketch / "ota_secrets.h").write_text(f'#define HOUSEPANEL_OTA_KEY_HEX "{KEY.hex()}"\n')
    fixtures = ROOT / "tools/tests/firmware"
    for name in ("WiFi.h", "Arduino_Portenta_OTA.h", "mbed.h", "hal/trng_api.h"):
        path = directory / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('#include "ota_runtime.h"\n')
    for name in ("aes", "md", "sha256"):
        path = directory / "mbedtls" / f"{name}.h"
        path.parent.mkdir(exist_ok=True)
        path.write_text('#include "ota_crypto.h"\n')
    binary = directory / "runtime"
    panel = request.param
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations",
        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(directory), "-I", str(fixtures),
        "-I", str(sketch), f'-DHOUSEPANEL_PANEL_ID="{panel}"', f'-DHOUSEPANEL_HOSTNAME="{ota.PANELS[panel][1]}"',
        str(fixtures / "ota_runtime_test.cpp"), str(sketch / "ota_update.cpp"),
        str(sketch / "ota_protocol.cpp"), "-Wl,--wrap=fopen", "-Wl,--wrap=remove", "-Wl,--wrap=rename",
        "-lcrypto", "-o", str(binary),
    ], check=True)
    return binary, panel


@pytest.mark.parametrize("mode", ["ok", "bad_auth", "expired", "timeout", "disconnect", "wifi_loss", "arm_failure", "bad_body", "status_soak"])
def test_actual_firmware_socket_staging_and_bootloader_boundary(runtime, tmp_path, mode):
    runtime, panel = runtime
    # Runtime fixture emits 16 boot bytes first, then this per-request nonce.
    challenge = bytes(range(16, 48)).hex()
    image = IMAGE.replace(ota.identity("primary"), ota.identity(panel))
    header, wire = ota.envelope(panel, challenge, image, KEY)
    if mode == "bad_auth":
        header = header[:-1] + bytes([header[-1] ^ 1])
    if mode == "bad_body":
        wire = wire[:-1] + bytes([wire[-1] ^ 1])
    payload = tmp_path / "envelope"
    payload.write_bytes(header + wire)
    reply = subprocess.check_output([runtime, payload, tmp_path, mode])
    body, tag = reply.splitlines(keepends=True)
    assert hmac.compare_digest(hmac.digest(ota.auth_key(KEY), body, "sha256").hex().encode(), tag.strip())
    status = json.loads(body)
    ota.verify_identity(status, panel)
    assert status["challenge"] == challenge and status["ready"] is True
    if mode == "ok":
        assert (tmp_path / "UPDATE.BIN").read_bytes() == image


@pytest.mark.parametrize("mode", ["init_layout", "init_bootloader", "init_storage", "init_entropy"])
def test_hardware_precondition_failure_disables_updates_without_retry_loop(runtime, tmp_path, mode):
    runtime, _ = runtime
    subprocess.run([runtime, tmp_path / "unused", tmp_path, mode], check=True)
