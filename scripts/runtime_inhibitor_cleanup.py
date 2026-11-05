#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect or remove an exact orphaned runtime application inhibitor.

This tool does not repair, recover, or adopt a runtime-controller deployment.
Cleanup is eligible only when the canonical WsprryPi service and every fixed
runtime-controller artifact are absent. Foreign or ambiguous state is retained.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any


SCHEMA = "rp1-gpclk-runtime-inhibitor-cleanup-v1"
INHIBITOR = "/etc/systemd/system/wsprrypi.service.d/90-rp1-route-inhibit.conf"
INHIBIT_BYTES = (
    b"# Owned by rp1-gpclk runtime administration\n"
    b"[Unit]\n"
    b"ConditionPathExists=/dev/null/rp1-route-inhibited\n"
)
SERVICE_UNITS = (
    "/etc/systemd/system/wsprrypi.service",
    "/run/systemd/system/wsprrypi.service",
    "/usr/local/lib/systemd/system/wsprrypi.service",
    "/usr/local/share/systemd/system/wsprrypi.service",
    "/usr/lib/systemd/system/wsprrypi.service",
    "/lib/systemd/system/wsprrypi.service",
)
RUNTIME_ARTIFACTS = (
    "/etc/rp1-gpclk-dkms/runtime-controller.json",
    "/etc/systemd/system/rp1-gpclk-route-manager@.service.d/95-runtime-controller.conf",
    "/var/lib/rp1-gpclk-dkms/runtime-admin",
    "/usr/lib/rp1-gpclk-dkms/runtime-uapi",
    "/usr/lib/rp1-gpclk-dkms/runtime-overlays",
    "/usr/lib/rp1-gpclk-dkms/runtime_application.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_activation.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_binding.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_controller_admin.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_deployment.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_layout.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_manager.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_output.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_provider.py",
    "/usr/lib/rp1-gpclk-dkms/runtime_route_client.py",
    "/usr/lib/rp1-gpclk-dkms/schema/rp1-gpclk-runtime-readiness-v1.schema.json",
    "/dev/rp1-route-admin",
    "/sys/module/rp1_route_controller",
    "/sys/module/rp1_gpclk_dkms",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def rooted(root: Path, absolute: str) -> Path:
    if not absolute.startswith("/"):
        raise ValueError("internal path is not absolute")
    return root / absolute.removeprefix("/")


def present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def trusted_parent(path: Path, root: Path, expected_uid: int) -> bool:
    try:
        relative = path.parent.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in (".", *relative.parts):
        if part != ".":
            current /= part
        try:
            info = current.lstat()
        except OSError:
            return False
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != expected_uid
            or expected_uid == 0 and info.st_gid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            return False
    return True


def inhibitor_state(path: Path, root: Path, expected_uid: int) -> str:
    if not present(path):
        return "absent"
    if not trusted_parent(path, root, expected_uid):
        return "foreign"
    try:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "foreign"
    try:
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "foreign"
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != expected_uid
                or expected_uid == 0 and info.st_gid != 0
                or stat.S_IMODE(info.st_mode) != 0o644
                or info.st_nlink != 1
                or info.st_size != len(INHIBIT_BYTES)
            ):
                return "foreign"
            data = os.read(fd, len(INHIBIT_BYTES) + 1)
            return "owned" if data == INHIBIT_BYTES else "foreign"
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def inspect(root: Path = Path("/"), expected_uid: int = 0) -> dict[str, Any]:
    inhibitor = rooted(root, INHIBITOR)
    services = sorted(
        str(path) for path in (rooted(root, item) for item in SERVICE_UNITS) if present(path)
    )
    residue = sorted(
        str(path) for path in (rooted(root, item) for item in RUNTIME_ARTIFACTS) if present(path)
    )
    result = {
        "schema": SCHEMA,
        "inhibitor": str(inhibitor),
        "inhibitorState": inhibitor_state(inhibitor, root, expected_uid),
        "serviceUnits": sorted(set(services)),
        "runtimeArtifacts": sorted(set(residue)),
    }
    result["orphanCleanupEligible"] = (
        result["inhibitorState"] == "owned"
        and not result["serviceUnits"]
        and not result["runtimeArtifacts"]
    )
    return result


def cleanup(
    approved: str,
    *,
    root: Path = Path("/"),
    expected_uid: int = 0,
    reload_systemd: bool = True,
) -> dict[str, Any]:
    plan = inspect(root, expected_uid)
    if digest(plan) != approved:
        raise ValueError("reviewed cleanup plan digest differs from current state")
    if not plan["orphanCleanupEligible"]:
        raise ValueError("runtime application inhibitor is not a proven orphan; preserve it")
    inhibitor = rooted(root, INHIBITOR)
    if not trusted_parent(inhibitor, root, expected_uid):
        raise ValueError("runtime application inhibitor parent is not trusted")
    directory_fd = os.open(inhibitor.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            inhibitor.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        try:
            info = os.fstat(fd)
            data = os.read(fd, len(INHIBIT_BYTES) + 1)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != expected_uid
                or expected_uid == 0 and info.st_gid != 0
                or stat.S_IMODE(info.st_mode) != 0o644
                or info.st_nlink != 1
                or data != INHIBIT_BYTES
            ):
                raise ValueError("runtime application inhibitor changed before cleanup")
            current = os.stat(inhibitor.name, dir_fd=directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("runtime application inhibitor identity changed before cleanup")
            os.unlink(inhibitor.name, dir_fd=directory_fd)
        finally:
            os.close(fd)
        os.fsync(directory_fd)
        if reload_systemd:
            try:
                subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True)
            except BaseException:
                restore = os.open(
                    inhibitor.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=directory_fd,
                )
                try:
                    os.fchown(restore, expected_uid, 0 if expected_uid == 0 else os.getegid())
                    os.write(restore, INHIBIT_BYTES)
                    os.fsync(restore)
                finally:
                    os.close(restore)
                os.fsync(directory_fd)
                subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=False)
                raise
    finally:
        os.close(directory_fd)
    try:
        inhibitor.parent.rmdir()
    except OSError as error:
        if error.errno not in (errno.ENOTEMPTY, errno.ENOENT):
            raise
    result = inspect(root, expected_uid)
    if result["inhibitorState"] != "absent":
        raise ValueError("runtime application inhibitor remains after cleanup")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "cleanup"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("root required for canonical ownership inspection")
    plan = inspect()
    plan_digest = digest(plan)
    if args.operation == "inspect" or not args.execute:
        print(json.dumps({"planSha256": plan_digest, "state": plan}, indent=2))
        return
    if not args.plan_sha256:
        raise ValueError("--plan-sha256 is required with --execute")
    result = cleanup(args.plan_sha256)
    print(json.dumps({"status": "removed-owned-orphan", "state": result}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit("STOP: " + str(error))
