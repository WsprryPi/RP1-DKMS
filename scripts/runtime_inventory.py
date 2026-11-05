#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded Linux runtime-route inventory. No endpoint access or mutation.

This collector is intentionally usable over stdin without installation. Its
output is observation evidence, never a switching authorization or admission
token. No caller-selected target paths or commands are accepted by the CLI.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import selectors
import stat
import struct
import subprocess
import sys
import time

LIMIT = 1024 * 1024
MODULE_LIMIT = 32 * LIMIT
TIMEOUT = 5
COMMANDS = {
    "kernel": ("/usr/bin/uname", "-r"),
    "architecture": ("/usr/bin/uname", "-m"),
    "packages": ("/usr/bin/dpkg-query", "-W", "-f=${binary:Package} ${Version} ${source:Package} ${source:Version}\n",
                 "rp1-gpclk-dkms", "raspi-utils-dt"),
    "services": ("/usr/bin/systemctl", "show", "wsprrypi.service", "soapyremote-server.service",
                 "rp1-gpclk-route-manager.socket", "--property=Id,ActiveState,UnitFileState,User,Group,Restart,FragmentPath,DropInPaths"),
    "managerUnit": ("/usr/bin/systemctl", "cat", "rp1-gpclk-route-manager@.service"),
    "installedModule": ("/usr/sbin/modinfo", "rp1_gpclk_dkms"),
}
FILES = {
    "bootId": "/proc/sys/kernel/random/boot_id",
    "bootConfig": "/boot/firmware/config.txt",
    "loadedVersion": "/sys/module/rp1_gpclk_dkms/version",
    "loadedSourceVersion": "/sys/module/rp1_gpclk_dkms/srcversion",
    "outputInhibit": "/sys/module/rp1_gpclk_dkms/parameters/output_inhibit",
    "moduleReferences": "/sys/module/rp1_gpclk_dkms/refcnt",
    "loadedBuildNote": "/sys/module/rp1_gpclk_dkms/notes/.note.gnu.build-id",
    "bootloaderVersion": "/sys/firmware/devicetree/base/chosen/bootloader/version",
    "model": "/sys/firmware/devicetree/base/model",
    "packagedManager": "/usr/sbin/rp1-gpclk-route-manager",
    "overlayTool": "/usr/bin/dtoverlay",
    "gpio4Overlay": "/boot/firmware/overlays/rp1-gpclk-gpio4.dtbo",
    "gpio20Overlay": "/boot/firmware/overlays/rp1-gpclk-gpio20.dtbo",
    "developmentRecord": "/var/lib/rp1-gpclk-dkms/development/route-manager.json",
}
TEXT_FILES = {"bootId", "bootConfig", "loadedVersion", "loadedSourceVersion", "outputInhibit",
              "moduleReferences", "bootloaderVersion", "model", "developmentRecord"}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def unknown(reason: str) -> dict:
    return {"status": "unknown", "reason": reason}


def bounded_command(argv: tuple[str, ...], *, timeout: float = TIMEOUT,
                    limit: int = 65536) -> dict:
    """Internal fixed-command runner; test injection is not exposed by CLI."""
    process, result, primary = None, None, None
    def unknown_result(reason):
        nonlocal result
        result = unknown(reason)
        return result
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                                                                 "LC_ALL": "C", "SYSTEMD_PAGER": "cat"})
        output = bytearray()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return unknown_result("command-timeout")
                chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    return unknown_result("command-output-limit")
        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        result = {"status": "unknown", "reason": "command-failed", "exitCode": code,
                  "text": output.decode(errors="replace")} if code else {
                      "status": "observed", "text": output.decode(errors="replace")}
        return result
    except (OSError, subprocess.TimeoutExpired) as error:
        return unknown_result("command-timeout" if isinstance(error, subprocess.TimeoutExpired) else type(error).__name__)
    except BaseException as error:
        primary = error
        raise
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as error:
                if result is not None:
                    result.update(status="unknown", cleanup={"status": "unresolved", "error": str(error)})
                elif primary is not None:
                    primary.add_note('secondary direct-child cleanup unresolved: '+str(error))
                else:
                    raise
            finally:
                process.stdout.close()


class Reader:
    """Read only regular files; never open a device endpoint or follow a leaf link."""
    def read(self, name: str, limit: int = LIMIT) -> bytes:
        if not stat.S_ISREG(os.lstat(name).st_mode):
            raise ValueError("not-regular-file")
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("not-regular-file")
            data = bytearray()
            while len(data) <= limit:
                piece = os.read(fd, min(65536, limit + 1 - len(data)))
                if not piece:
                    return bytes(data)
                data.extend(piece)
            raise ValueError("file-size-limit")
        finally:
            os.close(fd)

    def entries(self, name: str) -> list[str]:
        values = []
        with os.scandir(name) as directory:
            for item in directory:
                if len(values) == 256:
                    raise ValueError("directory-entry-limit")
                values.append(item.name)
        return sorted(values)

    def endpoints(self) -> list[dict]:
        root = Path("/sys/firmware/devicetree/base")
        if not root.is_dir():
            raise FileNotFoundError("device-tree-unavailable")
        count = 0
        result = []
        def failed(error):
            raise error
        for directory, children, files in os.walk(root, followlinks=False, onerror=failed):
            count += 1
            if count > 8192 or len(Path(directory).relative_to(root).parts) > 32:
                raise ValueError("device-tree-limit")
            if "compatible" not in files:
                continue
            compatible = self.read(str(Path(directory) / "compatible"), 4096)
            if b"wsprrypi,rp1-gpclk-dkms-v1" not in compatible.split(b"\0"):
                continue
            item = {"path": str(directory)}
            for name in ("status", "wsprrypi,route", "wsprrypi,pin"):
                try:
                    item[name] = self.read(str(Path(directory) / name), 4096).hex()
                except FileNotFoundError:
                    item[name] = None
            result.append(item)
        return result


def file_record(reader: Reader, name: str, text: bool = False, limit: int = LIMIT) -> dict:
    try:
        data = reader.read(name, limit)
        result = {"status": "observed", "path": name, "sha256": sha(data), "bytes": len(data)}
        if text:
            result["text"] = data.decode("utf-8").rstrip("\0\n")
        return result
    except (OSError, ValueError) as error:
        return {"path": name, **unknown(type(error).__name__)}


def module_note(blob: bytes) -> bytes:
    """Read the GNU build-note section of a bounded ELF64 little-endian module."""
    if len(blob) < 64 or blob[:6] != b"\x7fELF\x02\x01":
        raise ValueError("unsupported-elf")
    offset = struct.unpack_from("<Q", blob, 40)[0]
    width, count, names = struct.unpack_from("<HHH", blob, 58)
    if width != 64 or not 0 < count <= 8192 or names >= count or offset + width * count > len(blob):
        raise ValueError("elf-section-bounds")
    def section(index):
        record = struct.unpack_from("<IIQQQQIIQQ", blob, offset + width * index)
        start, size = record[4:6]
        if start + size > len(blob):
            raise ValueError("elf-data-bounds")
        return record, blob[start:start + size]
    _, strings = section(names)
    matches = []
    for index in range(count):
        record = struct.unpack_from("<IIQQQQIIQQ", blob, offset + width * index)
        if record[0] >= len(strings):
            raise ValueError("elf-name-bounds")
        end = strings.find(b"\0", record[0])
        if end < 0:
            raise ValueError("elf-name-termination")
        if strings[record[0]:end] == b".note.gnu.build-id":
            if record[1] != 7:
                raise ValueError("not-note-section")
            matches.append(section(index)[1])
    if len(matches) != 1:
        raise ValueError("build-note-missing-or-ambiguous")
    return matches[0]


def assess(files: dict, commands: dict, runtime: dict, endpoints: dict) -> dict:
    """Conservative preflight: never infer ownership from overlay names."""
    blockers = ["overlay-removal-result-not-established", "runtime-switch-adapter-not-implemented"]
    config = files.get("bootConfig", {})
    candidates = []
    boot_parse = "unknown"
    if config.get("status") == "observed":
        text = config["text"]
        # This is detection only, NOT a firmware config interpreter. Includes,
        # conditionals and parameters require separate effective-route evidence.
        candidates = re.findall(r"(?m)^\s*dtoverlay\s*=\s*rp1-gpclk-(gpio4|gpio20)(?:\s|,|$)", text)
        boot_parse = "candidates-only"
        if candidates:
            blockers.append("boot-route-migration-review-required")
    if runtime.get("status") != "observed" or endpoints.get("status") != "observed":
        blockers.append("route-observation-incomplete")
    if (files.get("outputInhibit", {}).get("status") == "observed" and
            files.get("outputInhibit", {}).get("text") not in ("0", "N", "1", "Y")):
        blockers.append("output-inhibit-state-unknown")
    return {"mutationAvailable": False, "qualification": False,
            "bootSelectionInterpretation": boot_parse, "bootRouteCandidates": candidates,
            "runtimeOwnership": "not-established", "operationalReady": "unknown",
            "loadedBytesIdentity": "not-established", "blockers": blockers}


def collect(reader: Reader | None = None, runner=bounded_command) -> dict:
    reader = reader or Reader()
    files = {key: file_record(reader, path, key in TEXT_FILES) for key, path in FILES.items()}
    commands = {key: runner(argv) for key, argv in COMMANDS.items()}
    kernel = commands["kernel"].get("text", "").strip()
    kernel_valid = (commands["kernel"].get("status") == "observed" and
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", kernel) is not None)
    if kernel_valid:
        files["kernelConfig"] = file_record(reader, "/boot/config-" + kernel)
    for key, path in (("runtimeOverlays", "/sys/kernel/config/device-tree/overlays"),
                      ("platformBindings", "/sys/bus/platform/drivers/rp1-gpclk-dkms")):
        try:
            files[key] = {"status": "observed", "entries": reader.entries(path)}
        except (OSError, ValueError) as error:
            files[key] = unknown(type(error).__name__)
    try:
        endpoints = {"status": "observed", "entries": reader.endpoints()}
    except (OSError, ValueError) as error:
        endpoints = unknown(type(error).__name__)
    # Only an exact modinfo path for the observed kernel may select module bytes.
    metadata = commands["installedModule"]
    paths = re.findall(r"(?m)^filename:\s*(\S+)\s*$", metadata.get("text", ""))
    if (kernel_valid and metadata.get("status") == "observed" and len(paths) == 1 and
            paths[0] == f"/lib/modules/{kernel}/updates/dkms/rp1_gpclk_dkms.ko.xz"):
        try:
            packed = reader.read(paths[0], MODULE_LIMIT)
            decoder = lzma.LZMADecompressor(memlimit=64 * LIMIT)
            unpacked = decoder.decompress(packed, max_length=MODULE_LIMIT + 1)
            if len(unpacked) > MODULE_LIMIT or not decoder.eof or decoder.unused_data:
                raise ValueError("module-decompression-bounds")
            note = module_note(unpacked)
            files["installedModuleBytes"] = {"status": "observed", "path": paths[0],
                "sha256": sha(packed), "decompressedSha256": sha(unpacked), "buildNoteSha256": sha(note),
                "buildNoteMatchesLoaded": (files["loadedBuildNote"].get("sha256") == sha(note)
                                           if files["loadedBuildNote"].get("status") == "observed" else None)}
        except (OSError, ValueError, lzma.LZMAError) as error:
            files["installedModuleBytes"] = unknown(type(error).__name__)
    else:
        files["installedModuleBytes"] = unknown("module-path-not-authenticated")
    # Boot ID brackets the non-atomic inventory; consistency is not a lock.
    ending = file_record(reader, FILES["bootId"], True)
    same_boot = (files["bootId"].get("status") == "observed" and
                 ending.get("status") == "observed" and
                 re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", files["bootId"].get("text", "")) is not None and
                 files["bootId"].get("text") == ending.get("text"))
    return {"schemaVersion": 1, "classification": "read-only-inventory", "observedAtUtc":
            datetime.datetime.now(datetime.timezone.utc).isoformat(), "sameBoot": same_boot,
            "atomic": False, "files": files, "commands": commands, "endpoints": endpoints,
            "assessment": assess(files, commands, files["runtimeOverlays"], endpoints)}


def main() -> int:
    if len(sys.argv) != 1:
        print(json.dumps({"status": "rejected", "reason": "arguments-not-supported"}))
        return 2
    result = collect()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["sameBoot"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
