#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exact-source RP1-GPCLK-DKMS development lifecycle.

This deliberately does not create or consume release identity.  Mutating
operations write an attributable rollback record before changing host state.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import json
import lzma
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

PACKAGE = "rp1-gpclk-dkms"
CANONICAL_MODULE = "rp1_gpclk_dkms"
CONTROLLER_MODULE = "rp1_route_controller"
ENDPOINT = "/dev/rp1-gpclk"
SCHEMA = "rp1-gpclk-source-development-manifest"
ENROLLMENT_SCHEMA = "rp1-gpclk-development-enrollment-v1"
ROLLBACK_SCHEMA = "rp1-gpclk-development-rollback-v1"
STATE_BASE = pathlib.Path("/var/lib/rp1-gpclk-dkms/development")
ENROLLMENT_BASE = pathlib.Path("/etc/rp1-gpclk-dkms/development")
TOOL_PATHS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
ROUTES = {"gpio4": "rp1-gpclk-gpio4", "gpio20": "rp1-gpclk-gpio20"}
MODULE_SUFFIXES = (".ko", ".ko.xz", ".ko.zst", ".ko.gz", ".ko.bz2")


class Failure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def root_path(path: pathlib.Path | str) -> pathlib.Path:
    root = pathlib.Path(os.environ.get("RP1_GPCLK_DEVELOPMENT_ROOT", "/"))
    value = pathlib.Path(path)
    return root / str(value).lstrip("/") if root != pathlib.Path("/") and value.is_absolute() else value


def atomic_write(path: pathlib.Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(mode)
    os.replace(temporary, path)


def run(args: list[str], *, cwd: pathlib.Path | None = None, check: bool = True,
        capture: bool = True, log: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
    print("COMMAND " + " ".join(args), file=sys.stderr, flush=True)
    result = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None,
                            text=True, check=False, env={**os.environ, "LC_ALL": "C"})
    if log is not None:
        atomic_write(log, ((result.stdout or "") + (result.stderr or "")).encode(), 0o600)
    if capture:
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    if check and result.returncode:
        raise Failure(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


def tool(name: str, required: bool = True) -> str | None:
    override = os.environ.get(f"RP1_GPCLK_TOOL_{name.upper().replace('-', '_')}")
    candidates = ([override] if override else []) + [str(pathlib.Path(base) / name) for base in TOOL_PATHS]
    found = next((item for item in candidates if item and pathlib.Path(item).is_file() and os.access(item, os.X_OK)), None)
    if required and found is None:
        raise Failure(f"required tool unavailable: {name}; searched {', '.join(candidates)}")
    return found


def tool_inventory() -> dict[str, str | None]:
    result = {}
    for name in ("dkms", "modprobe", "modinfo", "depmod", "rmmod", "make", "cc", "gcc",
                 "sha256sum", "xz", "zstd", "systemctl", "dtoverlay", "dtc", "cpp"):
        result[name] = tool(name, False)
    return result


def git(source: pathlib.Path, *args: str) -> str:
    result = run([tool("git") or "git", "-C", str(source), *args])
    return result.stdout or ""


def inventory(base: pathlib.Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    result = []
    for name in sorted(relative_paths):
        path = base / name
        if path.is_symlink() or not path.is_file():
            raise Failure(f"tracked input is not a regular file: {name}")
        result.append({"path": name, "size": path.stat().st_size, "sha256": sha256(path)})
    return result


def canonical_module_version(source: pathlib.Path) -> str:
    path = source / "include/rp1_gpclk/version.h"
    if path.is_symlink() or not path.is_file():
        raise Failure("canonical source module version header is missing or substituted")
    declared = re.findall(
        r'^#define RP1_GPCLK_MODULE_VERSION "([^"]+)"$',
        path.read_text(),
        re.M,
    )
    if len(declared) != 1 or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]*", declared[0]):
        raise Failure("canonical source module version is missing, ambiguous, or invalid")
    return declared[0]


def render(source: pathlib.Path, output: pathlib.Path, allow_dirty: bool,
           runtime_controller: bool = False) -> pathlib.Path:
    source, output = source.resolve(), output.absolute()
    version = canonical_module_version(source)
    if output.exists():
        raise Failure(f"destination already exists: {output}")
    commit = git(source, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Failure("source is not at an exact Git commit")
    status = git(source, "status", "--porcelain=v1", "--untracked-files=all")
    dirty = bool(status)
    if dirty and not allow_dirty:
        raise Failure("source checkout is dirty; use --allow-dirty to record and render tracked changes")
    names = [item for item in git(source, "ls-files", "-z").split("\0") if item]
    raw = inventory(source, names)
    output.mkdir(parents=True, mode=0o755)
    try:
        for name in names:
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
            destination.chmod(stat.S_IMODE((source / name).stat().st_mode))
        dkms = output / "dkms.conf"
        before = dkms.read_bytes()
        expected = b'PACKAGE_VERSION="#MODULE_VERSION#"'
        if before.count(expected) != 1:
            raise Failure("dkms.conf does not contain exactly one maintained module-version placeholder")
        intermediate = before.replace(expected, f'PACKAGE_VERSION="{version}"'.encode())
        kernel_filter = re.compile(br'(?m)^BUILD_EXCLUSIVE_KERNEL="[^"]+"$')
        if len(kernel_filter.findall(intermediate)) != 1:
            raise Failure("dkms.conf does not contain exactly one kernel-name filter")
        after = kernel_filter.sub(b'BUILD_EXCLUSIVE_KERNEL=".*"', intermediate)
        transformations = [
            {"path":"dkms.conf","operation":"replace-module-version-placeholder","beforeSha256":sha256_bytes(before),"afterSha256":sha256_bytes(intermediate)},
            {"path":"dkms.conf","operation":"relax-development-kernel-name-filter","beforeSha256":sha256_bytes(intermediate),"afterSha256":sha256_bytes(after)},
        ]
        if runtime_controller:
            runtime_before = after
            make = b'MAKE[0]="make KERNEL_BUILD=${kernel_source_dir}"'
            if after.count(make) != 1:
                raise Failure("dkms.conf does not contain exactly one maintained build command")
            after = after.replace(make,
                b'MAKE[0]="make KERNEL_BUILD=${kernel_source_dir} RP1_RUNTIME_CONTROLLER=1"')
            anchor = b'DEST_MODULE_LOCATION[0]="/updates/dkms"'
            if after.count(anchor) != 1:
                raise Failure("dkms.conf does not contain exactly one maintained module destination")
            after = after.replace(anchor, anchor + b'\n\nBUILT_MODULE_NAME[1]="rp1_route_controller"\n'
                b'BUILT_MODULE_LOCATION[1]="."\nDEST_MODULE_LOCATION[1]="/updates/dkms"')
            autoinstall = b'AUTOINSTALL="yes"'
            if after.count(autoinstall) != 1:
                raise Failure("dkms.conf does not contain exactly one maintained autoinstall policy")
            after = after.replace(autoinstall, b'AUTOINSTALL="no"')
            transformations.append({"path":"dkms.conf","operation":"select-runtime-controller-profile",
                "beforeSha256":sha256_bytes(runtime_before),"afterSha256":sha256_bytes(after)})
        dkms.write_bytes(after)
        unresolved = []
        for name in names:
            data = (output / name).read_bytes()
            if re.search(br'(?m)^PACKAGE_VERSION="#[A-Z0-9_]+#"$', data):
                unresolved.append(name)
        if unresolved:
            raise Failure("unresolved module-version placeholder: " + ", ".join(unresolved))
        rendered = inventory(output, names)
        changes = []
        raw_by_name = {item["path"]: item for item in raw}
        for item in rendered:
            if item["sha256"] != raw_by_name[item["path"]]["sha256"]:
                changes.append({"path": item["path"], "beforeSha256": raw_by_name[item["path"]]["sha256"],
                                "afterSha256": item["sha256"], "operation": "replace-module-version-placeholder"})
        if [item["path"] for item in changes] != ["dkms.conf"]:
            raise Failure("renderer performed an unapproved transformation")
        repository_url = run([tool("git") or "git", "-C", str(source), "config", "--get", "remote.origin.url"], check=False).stdout.strip()
        manifest = {
            "schema": SCHEMA, "classification": "source-development", "qualification": False,
            "createdAtUnix": int(time.time()), "repository": str(source),
            "repositoryUrl": repository_url or None,
            "sourceCommit": commit,
            "sourceState": "dirty-explicitly-allowed" if dirty else "clean", "sourceStatus": status.splitlines(),
            "renderedVersion": version, "packageName": PACKAGE, "dkmsName": PACKAGE,
            "moduleName": CANONICAL_MODULE, "renderedTree": str(output),
            "buildProfile": "runtime-controller" if runtime_controller else "ordinary",
            "versionIdentity": {"path":"include/rp1_gpclk/version.h",
                                "sha256":sha256(output/"include/rp1_gpclk/version.h"),
                                "moduleVersion":version},
            "rawInventory": raw, "renderedInventory": rendered, "transformations": transformations,
            "changedFiles":["dkms.conf"],
            "uapiIdentity": {"path":"include/uapi/linux/rp1_gpclk.h", "sha256":sha256(output/"include/uapi/linux/rp1_gpclk.h")},
            "overlayIdentity": {route:{"path":f"overlays/rp1-gpclk-{route}.dts", "sha256":sha256(output/f"overlays/rp1-gpclk-{route}.dts")} for route in ROUTES},
            "compatibilityIdentity": {"path":"src/rp1_gpclk_compatibility.c", "sha256":sha256(output/"src/rp1_gpclk_compatibility.c")},
            "releaseIdentity": None, "releaseQualified": False,
        }
        path = output / "DEVELOPMENT_MANIFEST.json"
        atomic_write(path, canonical(manifest), 0o644)
        return path
    except BaseException:
        shutil.rmtree(output)
        raise


def load_manifest(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise Failure(f"development manifest is unreadable: {error}") from error
    if value.get("schema") != SCHEMA or value.get("classification") != "source-development" or value.get("qualification") is not False:
        raise Failure("not a valid source-development manifest")
    if value.get("moduleName") != CANONICAL_MODULE or value.get("dkmsName") != PACKAGE:
        raise Failure("manifest module identity mismatch")
    if "buildProfile" not in value:
        value["buildProfile"] = "ordinary"
    if value.get("buildProfile") not in {"ordinary", "runtime-controller"}:
        raise Failure("manifest build profile is invalid")
    return value


def compression(path: pathlib.Path) -> str:
    return "none" if path.name.endswith(".ko") else path.suffix.lstrip(".")


def decompressed(path: pathlib.Path) -> bytes:
    data = path.read_bytes()
    kind = compression(path)
    if kind == "none": return data
    if kind == "xz": return lzma.decompress(data)
    if kind == "gz": return gzip.decompress(data)
    if kind == "bz2": return bz2.decompress(data)
    if kind == "zst":
        zstd = tool("zstd")
        result = subprocess.run([zstd or "zstd", "-q", "-d", "-c", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode: raise Failure(f"zstd decompression failed: {result.stderr.decode(errors='replace')}")
        return result.stdout
    raise Failure(f"unsupported module compression: {kind}")


def module_candidates(kernel: str, module: str = CANONICAL_MODULE) -> list[pathlib.Path]:
    base = root_path(f"/lib/modules/{kernel}")
    return sorted(path for path in base.rglob(f"{module}.ko*")
                  if path.is_file() and any(path.name.endswith(s) for s in MODULE_SUFFIXES)) if base.is_dir() else []


def modinfo(path: pathlib.Path, field: str) -> str:
    result = run([tool("modinfo") or "modinfo", "-F", field, str(path)], check=False)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def resolve_module(kernel: str, expected_version: str | None = None,
                   module: str = CANONICAL_MODULE) -> dict[str, Any]:
    matches = []
    for path in module_candidates(kernel, module):
        name = modinfo(path, "name")
        if name != module:
            raise Failure(f"foreign or unreadable module at canonical path: {path}")
        matches.append((path, name))
    if len(matches) != 1:
        raise Failure(f"expected exactly one installed {module} artifact for {kernel}; found {len(matches)}")
    path, name = matches[0]
    version = modinfo(path, "version")
    if expected_version and version != expected_version:
        raise Failure(f"installed module version mismatch: expected {expected_version}, got {version or 'absent'}")
    elf = decompressed(path)
    if not elf.startswith(b"\x7fELF"):
        raise Failure("installed module does not decompress to ELF")
    return {"installedPath": str(path), "installedFileSha256": sha256(path), "compression": compression(path),
            "decompressedElfSha256": sha256_bytes(elf), "moduleName": name, "moduleVersion": version,
            "kernel": kernel,
            "vermagic": modinfo(path, "vermagic"), "signer": modinfo(path, "signer"),
            "signatureKey": modinfo(path, "sig_key"), "signatureHashAlgorithm": modinfo(path, "sig_hashalgo"),
            "signatureState": "signed" if modinfo(path, "signer") else "unsigned"}


def kernel_identities(requested: str) -> dict[str, Any]:
    running = platform.release()
    headers = root_path(f"/lib/modules/{requested}/build")
    boot = root_path("/boot/firmware").exists()
    loaded = root_path(f"/sys/module/{CANONICAL_MODULE}").exists()
    return {"runningKernel": running, "requestedBuildKernel": requested,
            "headersKernel": requested if headers.exists() else None,
            "installedModuleKernel": requested if module_candidates(requested) else None,
            "bootSelectedKernel": requested if boot and requested == running else "not-reliably-discoverable",
            "loadedModuleKernel": running if loaded else None}


def print_mutation_identity(kernel: str, artifact: str | None = None) -> None:
    print(json.dumps({"resolvedModuleName": CANONICAL_MODULE, "installedArtifact": artifact,
                      "targetKernel": kernel}, sort_keys=True), file=sys.stderr)


def require_root() -> None:
    if os.environ.get("RP1_GPCLK_DEVELOPMENT_TEST_ROOT") != "1" and os.geteuid() != 0:
        raise Failure("mutation requires root")


def update_manifest(path: pathlib.Path, additions: dict[str, Any]) -> dict[str, Any]:
    value = load_manifest(path)
    value.update(additions)
    atomic_write(path, canonical(value), 0o644)
    return value


def owned_source(path: pathlib.Path, version: str) -> dict[str, Any]:
    """Prove a replaceable development tree; package/foreign trees are not ours."""
    if path.is_symlink() or not path.is_dir():
        raise Failure(f"foreign source path: {path}")
    manifest_path = path / "DEVELOPMENT_MANIFEST.json"
    if manifest_path.is_symlink():
        raise Failure("foreign source manifest symlink")
    value = load_manifest(manifest_path)
    if value.get("renderedVersion") != version:
        raise Failure("source version ownership mismatch")
    expected = value.get("renderedInventory")
    if not isinstance(expected, list) or not expected:
        raise Failure("source ownership inventory missing")
    if not all(isinstance(item, dict) and isinstance(item.get("path"), str)
               and isinstance(item.get("size"), int) and isinstance(item.get("sha256"), str)
               for item in expected):
        raise Failure("source ownership inventory malformed")
    names = [item["path"] for item in expected]
    if any(p.is_symlink() for p in path.rglob("*")):
        raise Failure("foreign source symlink")
    if any(p.stat().st_uid != os.geteuid() or p.stat().st_mode & 0o022
           for p in [path, *path.rglob("*")]):
        raise Failure("foreign source ownership or writable permissions")
    if any(pathlib.PurePosixPath(n).is_absolute() or ".." in pathlib.PurePosixPath(n).parts for n in names):
        raise Failure("source inventory escapes owned tree")
    actual = sorted(str(p.relative_to(path)) for p in path.rglob("*") if not p.is_dir())
    if actual != sorted(names + ["DEVELOPMENT_MANIFEST.json"]) or inventory(path, names) != expected:
        raise Failure("foreign or modified development source; retain for maintainer review")
    return value


def transition_preflight(version: str, kernel: str, dkms_status: list[str],
                         expected_modules: tuple[str, ...] = (CANONICAL_MODULE,)) -> pathlib.Path | None:
    """Never implicitly downgrade, take package ownership, or hide stale instances."""
    destination = root_path(f"/usr/src/{PACKAGE}-{version}")
    for line in dkms_status:
        match = re.match(r"rp1-gpclk-dkms/([^,\s]+)(?:,|:)", line)
        if not match or match.group(1) != version:
            raise Failure("predecessor/unknown DKMS instance: explicit maintainer downgrade migration required")
        if "," in line and line.split(",")[1].strip() != kernel:
            raise Failure("DKMS instance for another kernel: explicit migration required")
    for path in root_path("/usr/src").glob(f"{PACKAGE}-*"):
        if path != destination:
            raise Failure(f"stale predecessor source {path}: explicit maintainer downgrade migration required")
    # Binding/enrollment restoration has its own exact-byte transaction. Never
    # make it stale as a side effect of the source installer.
    for path in (root_path(ENROLLMENT_BASE), root_path(STATE_BASE.parent / "runtime-admin")):
        if path.exists() and any(path.iterdir()):
            raise Failure(f"retained enrollment/runtime state {path}: explicit migration required")
    for name in ("/etc/rp1-gpclk-dkms/runtime-controller.json",
                 "/var/lib/rp1-gpclk-dkms/development/route-manager.json",
                 "/var/lib/dpkg/info/rp1-gpclk-dkms.list"):
        if root_path(name).exists():
            raise Failure(f"retained package/manager ownership {name}: explicit migration required")
    loaded = root_path(f"/sys/module/{CANONICAL_MODULE}/version")
    loaded_controller = root_path(f"/sys/module/{CONTROLLER_MODULE}/version")
    if loaded.parent.exists() and not loaded.is_file():
        raise Failure("loaded module version unavailable: explicit migration required")
    if loaded.exists() and loaded.read_text().strip() != version:
        raise Failure("loaded predecessor: explicit maintainer downgrade migration required")
    if loaded_controller.parent.exists() and not loaded_controller.is_file():
        raise Failure("loaded controller version unavailable: explicit migration required")
    if loaded_controller.exists() and loaded_controller.read_text().strip() != version:
        raise Failure("loaded controller predecessor: explicit maintainer migration required")
    candidates = {name: module_candidates(kernel, name)
                  for name in (CANONICAL_MODULE, CONTROLLER_MODULE)}
    for name in expected_modules:
        if candidates[name]:
            resolve_module(kernel, version, name)
    unexpected = set(candidates) - set(expected_modules)
    if any(candidates[name] for name in unexpected):
        raise Failure("installed module set differs from the selected development profile")
    if destination.exists() or destination.is_symlink():
        owned_source(destination, version)
        return destination
    if dkms_status or any(candidates.values()) or loaded.exists() or loaded_controller.exists():
        raise Failure("orphan module/DKMS instance without attributable development source")
    return None


def route_neutral_observation() -> dict[str, Any]:
    configured: list[dict[str, str]] = []
    for name in ("/boot/firmware/config.txt", "/boot/config.txt"):
        config = root_path(name)
        if config.is_symlink():
            configured.append({"path": str(config), "route": "unsafe-symlink"})
        elif config.is_file():
            text = config.read_text(errors="replace")
            for route in re.findall(
                    r"(?m)^\s*dtoverlay\s*=\s*rp1-gpclk-(gpio4|gpio20)(?:\s|,|$)", text):
                configured.append({"path": str(config), "route": route})

    active: list[str] = []
    tree = root_path("/sys/firmware/devicetree/base")
    if tree.is_dir():
        for route in ROUTES:
            if any(path.name == f"rp1-gpclk-dkms-{route}"
                   for path in tree.rglob(f"rp1-gpclk-dkms-{route}")):
                active.append(route)
        if any(path.name == "rp1-gpclk-dkms"
               for path in tree.rglob("rp1-gpclk-dkms")):
            active.append("predecessor-shared-node")

    overlay_files = []
    for base in ("/boot/firmware/overlays", "/boot/overlays",
                 "/usr/lib/rp1-gpclk-dkms/overlays"):
        for route in ROUTES:
            path = root_path(f"{base}/rp1-gpclk-{route}.dtbo")
            if path.exists() or path.is_symlink():
                overlay_files.append(str(path))
    for route in ROUTES:
        path = root_path(f"/usr/lib/rp1-gpclk-dkms/runtime-overlays/{route}.dtbo")
        if path.exists() or path.is_symlink():
            overlay_files.append(str(path))

    return {
        "configuredRoutes": configured,
        "activeRoutes": sorted(active),
        "loadedModule": root_path(f"/sys/module/{CANONICAL_MODULE}").exists(),
        "loadedRouteController": root_path("/sys/module/rp1_route_controller").exists(),
        "endpointPresent": root_path(ENDPOINT).exists(),
        "routeControllerEndpointPresent": root_path("/dev/rp1-route-admin").exists(),
        "historicalEndpointPresent": root_path("/dev/rp1-gpclk0").exists(),
        "routeOverlayFiles": sorted(overlay_files),
    }


def require_route_neutral(observation: dict[str, Any], stage: str) -> None:
    blockers = [name for name, value in observation.items() if value]
    if blockers:
        raise Failure(
            f"route-neutral {stage} requires no configured/active route, loaded consumer/controller, "
            f"RP1 endpoint, or installed route overlay; blockers: {', '.join(blockers)}")


def install(args: argparse.Namespace) -> dict[str, Any]:
    requested = args.kernel or platform.release()
    source = pathlib.Path(args.source).resolve()
    version = canonical_module_version(source)
    route_neutral = bool(getattr(args, "route_neutral", False))
    if route_neutral:
        if args.route is not None:
            raise Failure("route-neutral installation cannot select a GPIO route")
        if args.load:
            raise Failure("route-neutral installation cannot load the module")
        if args.output_inhibit != 1:
            raise Failure("route-neutral development requires output_inhibit=1")
        if args.allow_dirty:
            raise Failure("route-neutral installation requires a clean exact source commit")
        neutral_before = route_neutral_observation()
        require_route_neutral(neutral_before, "preflight")
    else:
        neutral_before = None
    identities, tools = kernel_identities(requested), tool_inventory()
    print(json.dumps({"kernels": identities, "tools": tools}, indent=2, sort_keys=True), file=sys.stderr)
    for required in ("make", "dkms", "depmod", "modinfo", "sha256sum"):
        if not tools[required]: raise Failure(f"required tool unavailable: {required}")
    if (args.load or root_path(f"/sys/module/{CANONICAL_MODULE}").exists()) and not tools["modprobe"]:
        raise Failure("required tool unavailable: modprobe")
    if identities["headersKernel"] is None:
        raise Failure(f"missing headers for requested kernel: /lib/modules/{requested}/build")
    evidence = pathlib.Path(args.evidence_directory).absolute()
    if evidence.exists(): raise Failure(f"evidence directory already exists: {evidence}")
    evidence.mkdir(parents=True, mode=0o755)
    rendered = evidence / "rendered-source"
    runtime_controller = bool(getattr(args, "runtime_controller", False))
    manifest_path = render(source, rendered, args.allow_dirty, runtime_controller)
    rollback_path = evidence / "ROLLBACK.json"
    expected_modules = (CANONICAL_MODULE, CONTROLLER_MODULE) if runtime_controller else (CANONICAL_MODULE,)
    before = {"dkmsStatus": run([tools["dkms"], "status", "-m", PACKAGE]).stdout.splitlines(),
              "installedArtifacts": [{"path": str(p), "sha256": sha256(p)}
                  for name in expected_modules for p in module_candidates(requested, name)],
              "loaded": root_path(f"/sys/module/{CANONICAL_MODULE}").exists(), "createdFiles": []}
    predecessor = transition_preflight(version, requested, before["dkmsStatus"], expected_modules)
    if predecessor is not None:
        shutil.copytree(predecessor, evidence / "prior-source")
    for index, item in enumerate(before["installedArtifacts"]):
        backup = evidence / f"prior-module-{index}{''.join(pathlib.Path(item['path']).suffixes)}"
        shutil.copyfile(item["path"], backup)
        item["backup"] = str(backup)
    rollback = {"schema": ROLLBACK_SCHEMA, "classification": "source-development", "manifest": str(manifest_path),
                "kernel": requested, "moduleName": CANONICAL_MODULE, "version": version,
                "prior": before, "workflowCreatedFiles": [], "status": "prepared"}
    rollback["priorSource"] = str(evidence / "prior-source") if predecessor else None
    atomic_write(rollback_path, canonical(rollback))
    install_requested = args.install or not args.build_only
    if args.build_only or install_requested:
        require_root()
        print_mutation_identity(requested)
        destination = root_path(f"/usr/src/{PACKAGE}-{version}")
        if destination.exists():
            if root_path(f"/sys/module/{CANONICAL_MODULE}").exists():
                run([tools["modprobe"], "-r", CANONICAL_MODULE], log=evidence / "module-unload-for-replace.log")
            if root_path(f"/sys/module/{CONTROLLER_MODULE}").exists():
                run([tools["modprobe"], "-r", CONTROLLER_MODULE], log=evidence / "controller-unload-for-replace.log")
            run([tools["dkms"], "remove", "-m", PACKAGE, "-v", version, "--all"], log=evidence / "dkms-remove.log")
            if destination.exists(): shutil.rmtree(destination)
        rollback["workflowCreatedFiles"].append(str(destination))
        rollback["sourceManifestSha256"] = sha256(manifest_path)
        rollback["status"] = "installing"
        atomic_write(rollback_path, canonical(rollback))
        shutil.copytree(rendered, destination)
        run([tools["dkms"], "add", "-m", PACKAGE, "-v", version], log=evidence / "dkms-add.log")
        run([tools["dkms"], "build", "-m", PACKAGE, "-v", version, "-k", requested], log=evidence / "dkms-build.log")
        if install_requested:
            run([tools["dkms"], "install", "-m", PACKAGE, "-v", version, "-k", requested], log=evidence / "dkms-install.log")
            run([tools["depmod"], "-a", requested], log=evidence / "depmod.log")
    installed_modules = ({name: resolve_module(requested, version, name)
                          for name in expected_modules} if install_requested else {})
    module = installed_modules.get(CANONICAL_MODULE)
    if runtime_controller and module:
        if modinfo(pathlib.Path(module["installedPath"]), "rp1_runtime_controller") != "1":
            raise Failure("runtime-profile consumer lacks controller interlock")
        dependencies = set(filter(None, modinfo(pathlib.Path(module["installedPath"]), "depends").split(',')))
        if CONTROLLER_MODULE not in dependencies:
            raise Failure("runtime-profile consumer lacks controller dependency")
        if modinfo(pathlib.Path(module["installedPath"]), "alias"):
            raise Failure("runtime-profile consumer unexpectedly retains an autoload alias")
    if module: print_mutation_identity(requested, module["installedPath"])
    neutral_after = route_neutral_observation() if route_neutral else None
    if neutral_after is not None:
        require_route_neutral(neutral_after, "verification")
    compiler = tools["cc"] or tools["gcc"]
    version_safe = {"dkms","modinfo","depmod","make","cc","gcc","sha256sum","xz","zstd","dtc","cpp"}
    tool_versions = {name:(run([path,"--version"],check=False).stdout or "").splitlines()[:1]
                     for name,path in tools.items() if path and name in version_safe}
    manifest = update_manifest(manifest_path, {"targetKernel": requested, "kernelIdentities": kernel_identities(requested),
        "architecture": platform.machine(), "headersPath":str(root_path(f"/lib/modules/{requested}/build")),
        "compiler":compiler, "toolVersions":tool_versions, "tools": tools, "installedModule": module,
        "installedModules": installed_modules, "route": args.route,
        "installationMode": "route-neutral" if route_neutral else "route-specific",
        "routeNeutralSafety": {"before": neutral_before, "after": neutral_after} if route_neutral else None,
        "parameters": {"output_inhibit": args.output_inhibit}, "buildLogs": sorted(str(p) for p in evidence.glob("*.log")),
        "dkmsStatus":run([tools["dkms"],"status","-m",PACKAGE,"-v",version],check=False).stdout.splitlines(),
        "rollbackRecord": str(rollback_path), "developmentState": "development-installed" if module else "development-built"})
    if args.load:
        if requested != platform.release(): raise Failure("cannot load a module built for a non-running kernel")
        lifecycle_action("load", manifest_path, args.output_inhibit)
        manifest = load_manifest(manifest_path)
    rollback["installedModules"] = installed_modules
    rollback["installedManifestSha256"] = sha256(manifest_path)
    rollback["buildProfile"] = "runtime-controller" if runtime_controller else "ordinary"
    rollback["status"] = "ready"; atomic_write(rollback_path, canonical(rollback))
    result = {"status": "ok", "classification": "source-development", "manifest": str(manifest_path),
              "rollback": str(rollback_path), "state": manifest.get("developmentState"), "module": module}
    atomic_write(evidence / "RESULT.json", canonical(result), 0o644)
    return result


def sysfs_parameter(name: str) -> str | None:
    path = root_path(f"/sys/module/{CANONICAL_MODULE}/parameters/{name}")
    return path.read_text().strip() if path.is_file() else None


def lifecycle_action(action: str, manifest_path: pathlib.Path, output_inhibit: int | None = None) -> dict[str, Any]:
    manifest = load_manifest(manifest_path); kernel = manifest.get("targetKernel")
    if not kernel: raise Failure("manifest has no target kernel")
    module = resolve_module(kernel, manifest["renderedVersion"])
    loaded = root_path(f"/sys/module/{CANONICAL_MODULE}").exists()
    if action == "status": return lifecycle_status(manifest_path)
    require_root(); print_mutation_identity(kernel, module["installedPath"])
    modprobe, depmod = tool("modprobe"), tool("depmod")
    if action in {"load", "reload"}:
        if kernel != platform.release(): raise Failure("requested module kernel is not running")
        if action == "reload" and loaded: run([modprobe or "modprobe", "-r", CANONICAL_MODULE])
        elif loaded: raise Failure("module is already loaded; use reload")
        run([depmod or "depmod", "-a", kernel])
        inhibited = 1 if output_inhibit is None else int(output_inhibit)
        run([modprobe or "modprobe", CANONICAL_MODULE, f"output_inhibit={inhibited}"])
        loaded_version_path = root_path(f"/sys/module/{CANONICAL_MODULE}/version")
        loaded_version = loaded_version_path.read_text().strip() if loaded_version_path.is_file() else None
        if loaded_version is not None and loaded_version != manifest["renderedVersion"]:
            raise Failure(f"loaded module version mismatch: expected {manifest['renderedVersion']}, got {loaded_version}")
        observed = sysfs_parameter("output_inhibit")
        expected = "Y" if inhibited else "N"
        if observed not in {expected, str(inhibited)}:
            raise Failure(f"loaded output_inhibit mismatch: expected {expected}, got {observed}")
        update_manifest(manifest_path, {"parameters": {"output_inhibit": inhibited},
                                       "developmentState": "development-output-inhibited" if inhibited else "development-output-capable"})
    elif action == "unload":
        if loaded: run([modprobe or "modprobe", "-r", CANONICAL_MODULE])
        if root_path(f"/sys/module/{CANONICAL_MODULE}").exists(): raise Failure("module remains loaded")
        update_manifest(manifest_path, {"developmentState": "development-installed"})
    else: raise Failure(f"unknown lifecycle action: {action}")
    return lifecycle_status(manifest_path)


def endpoint_status() -> dict[str, Any]:
    path = root_path(ENDPOINT)
    present = path.exists()
    metadata: dict[str, Any] = {"path": ENDPOINT, "present": present}
    if present:
        value = path.stat(); metadata.update(mode=f"{stat.S_IMODE(value.st_mode):04o}", uid=value.st_uid, gid=value.st_gid)
        if stat.S_ISCHR(value.st_mode): metadata.update(major=os.major(value.st_rdev), minor=os.minor(value.st_rdev))
    lsof = tool("lsof", False)
    metadata["openOwners"] = run([lsof, ENDPOINT], check=False).stdout.splitlines()[1:] if present and lsof else []
    return metadata


def lifecycle_status(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path); kernel = manifest.get("targetKernel") or platform.release()
    loaded = root_path(f"/sys/module/{CANONICAL_MODULE}").exists()
    endpoint = endpoint_status()
    state = "development-endpoint-ready" if loaded and endpoint["present"] else "development-loaded" if loaded else "development-installed" if module_candidates(kernel) else "development-built"
    if loaded and sysfs_parameter("output_inhibit") in {"Y", "1"}: state = "development-output-inhibited"
    elif loaded and sysfs_parameter("output_inhibit") in {"N", "0"}: state = "development-output-capable"
    module = None
    try: module = resolve_module(kernel, manifest["renderedVersion"])
    except Failure: pass
    return {"classification": "source-development", "releaseQualified": False, "developmentState": state,
            "nextAction": {"development-built":"install", "development-installed":"load", "development-loaded":"verify endpoint",
                           "development-endpoint-ready":"inspect output inhibit", "development-output-inhibited":"run lifecycle tests",
                           "development-output-capable":"use root-owned endpoint"}.get(state),
            "sourceCommit": manifest["sourceCommit"], "sourceState": manifest["sourceState"], "renderedVersion": manifest["renderedVersion"],
            "module": module, "loaded": loaded, "loadedParameters": {"output_inhibit": sysfs_parameter("output_inhibit")},
            "moduleRefcount": root_path(f"/sys/module/{CANONICAL_MODULE}/refcnt").read_text().strip() if root_path(f"/sys/module/{CANONICAL_MODULE}/refcnt").is_file() else None,
            "endpoint": endpoint, "kernels": kernel_identities(kernel), "route": manifest.get("route"),
            "enrollment": enrollment_status(manifest_path), "manifest": str(manifest_path)}


def enrollment_path(manifest: dict[str, Any]) -> pathlib.Path:
    return root_path(ENROLLMENT_BASE / f"{manifest['sourceCommit']}-{manifest['renderedVersion']}.json")


def development_identity(manifest: dict[str, Any]) -> str:
    fields = {name:manifest.get(name) for name in ("sourceCommit","sourceState","renderedVersion","moduleName",
              "targetKernel","route","uapiIdentity","overlayIdentity","compatibilityIdentity","installedModule")}
    return sha256_bytes(json.dumps(fields,sort_keys=True,separators=(",",":")).encode())


def enrollment_status(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path); path = enrollment_path(manifest)
    if not path.is_file(): return {"status": "absent", "path": str(path)}
    try: value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError): return {"status": "rejected", "path": str(path)}
    expected = {"sourceCommit": manifest["sourceCommit"], "moduleVersion": manifest["renderedVersion"],
                "moduleName": CANONICAL_MODULE, "kernel": manifest.get("targetKernel"), "route": manifest.get("route"),
                "developmentIdentitySha256":development_identity(manifest)}
    return {"status": "current" if all(value.get(k) == v for k, v in expected.items()) else "mismatch", "path": str(path), "record": value}


def enroll(manifest_path: pathlib.Path, route: str, kernel: str, remove: bool = False) -> dict[str, Any]:
    require_root(); manifest = load_manifest(manifest_path)
    if manifest.get("targetKernel") != kernel or manifest.get("route") != route:
        raise Failure("development enrollment kernel or route differs from manifest")
    path = enrollment_path(manifest)
    if remove:
        print_mutation_identity(kernel)
        if path.is_file(): path.unlink()
        return {"status": "removed", "path": str(path)}
    module = resolve_module(kernel, manifest["renderedVersion"])
    print_mutation_identity(kernel, module["installedPath"])
    record = {"schema": ENROLLMENT_SCHEMA, "classification": "Experimental", "qualification": False,
              "sourceCommit": manifest["sourceCommit"], "sourceManifestSha256": sha256(manifest_path),
              "developmentIdentitySha256":development_identity(manifest),
              "moduleName": CANONICAL_MODULE, "moduleVersion": manifest["renderedVersion"],
              "installedModule": module, "kernel": kernel, "route": route,
              "uapiIdentity": manifest.get("uapiIdentity"), "overlayIdentity": manifest.get("overlayIdentity"),
              "compatibilityIdentity": manifest.get("compatibilityIdentity"), "removalCommand": f"sudo ./scripts/development-enroll --remove --manifest {manifest_path} --route {route} --kernel {kernel}"}
    atomic_write(path, canonical(record), 0o644)
    return {"status": "enrolled", "path": str(path), "record": record}


def rollback(record_path: pathlib.Path) -> dict[str, Any]:
    require_root()
    try: record = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError) as error: raise Failure(f"rollback record unreadable: {error}") from error
    if record.get("schema") != ROLLBACK_SCHEMA: raise Failure("invalid rollback record")
    kernel, version = record["kernel"], record["version"]
    if (record.get("moduleName") != CANONICAL_MODULE or
            not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)):
        raise Failure("rollback module/version scope mismatch")
    allowed = root_path(f"/usr/src/{PACKAGE}-{version}")
    # Validate the entire removal scope BEFORE unloading or invoking DKMS.
    if record.get("workflowCreatedFiles") != [str(allowed)]:
        raise Failure("rollback record contains out-of-scope paths")
    owned_source(allowed, version)
    if sha256(allowed / "DEVELOPMENT_MANIFEST.json") != record.get("sourceManifestSha256"):
        raise Failure("rollback source has been replaced by another instance")
    loaded = root_path(f"/sys/module/{CANONICAL_MODULE}/version")
    loaded_controller = root_path(f"/sys/module/{CONTROLLER_MODULE}/version")
    if loaded.exists() and loaded.read_text().strip() != version:
        raise Failure("rollback refuses to unload a different version")
    if loaded_controller.parent.exists() and not loaded_controller.is_file():
        raise Failure("rollback controller version is unavailable")
    if loaded_controller.exists() and loaded_controller.read_text().strip() != version:
        raise Failure("rollback refuses to unload a different controller version")
    expected_names = ((CANONICAL_MODULE, CONTROLLER_MODULE)
                      if record.get("buildProfile") == "runtime-controller"
                      else (CANONICAL_MODULE,))
    installed = record.get("installedModules")
    if not isinstance(installed, dict) or set(installed) != set(expected_names):
        raise Failure("rollback installed module set ownership mismatch")
    for name in expected_names:
        current = resolve_module(kernel, version, name)
        expected = installed[name]
        if (not isinstance(expected, dict)
                or current["installedPath"] != expected.get("installedPath")
                or current["installedFileSha256"] != expected.get("installedFileSha256")
                or current["decompressedElfSha256"] != expected.get("decompressedElfSha256")):
            raise Failure(f"rollback installed {name} artifact ownership mismatch")
    unexpected = set((CANONICAL_MODULE, CONTROLLER_MODULE)) - set(expected_names)
    if any(module_candidates(kernel, name) for name in unexpected):
        raise Failure("rollback installed module set contains an unowned artifact")
    status = run([tool("dkms") or "dkms", "status", "-m", PACKAGE]).stdout.splitlines()
    transition_preflight(version, kernel, status, expected_names)
    print_mutation_identity(kernel)
    if root_path(f"/sys/module/{CANONICAL_MODULE}").exists(): run([tool("modprobe") or "modprobe", "-r", CANONICAL_MODULE])
    if root_path(f"/sys/module/{CONTROLLER_MODULE}").exists(): run([tool("modprobe") or "modprobe", "-r", CONTROLLER_MODULE])
    run([tool("dkms") or "dkms", "remove", "-m", PACKAGE, "-v", version, "--all"])
    for name in record.get("workflowCreatedFiles", []):
        path = pathlib.Path(name)
        allowed = root_path(f"/usr/src/{PACKAGE}-{version}")
        if path != allowed: raise Failure(f"rollback record contains out-of-scope path: {path}")
        if path.is_dir(): shutil.rmtree(path)
    run([tool("depmod") or "depmod", "-a", kernel])
    record["status"] = "rolled-back"; atomic_write(record_path, canonical(record))
    return {"status": "rolled-back", "record": str(record_path), "scope": "recorded-objects-only"}


def route_observation(manifest_path: pathlib.Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path); requested = manifest.get("route")
    enrollment = enrollment_status(manifest_path)
    config = root_path("/boot/firmware/config.txt")
    configured = []
    if config.is_file():
        text = config.read_text(errors="replace")
        configured = [route for route, overlay in ROUTES.items() if re.search(rf"(?m)^dtoverlay={re.escape(overlay)}\s*$", text)]
    active = []
    tree = root_path("/sys/firmware/devicetree/base")
    if tree.is_dir():
        for route in ROUTES:
            if any(path.name == f"rp1-gpclk-dkms-{route}" for path in tree.rglob(f"rp1-gpclk-dkms-{route}")):
                active.append(route)
    module_route = None
    route_parameter = root_path(f"/sys/module/{CANONICAL_MODULE}/parameters/route")
    if route_parameter.is_file(): module_route = route_parameter.read_text().strip().lower()
    endpoint = endpoint_status()
    configured_route = configured[0] if len(configured) == 1 else "ambiguous" if configured else None
    active_route = active[0] if len(active) == 1 else "ambiguous" if active else None
    operational = (requested is not None and configured_route == active_route == requested and
                   module_route in {None, requested} and endpoint["present"])
    inhibited = sysfs_parameter("output_inhibit") in {"Y", "1"}
    return {"requestedRoute": requested, "savedRoute": enrollment.get("record", {}).get("route"),
            "configuredRoute": configured_route, "overlayActiveRoute": active_route,
            "moduleReportedRoute": module_route, "endpoint": endpoint,
            "operationalRoute": requested if operational else None,
            "outputInhibited": inhibited,
            "classification": "Experimental", "releaseQualified": False,
            "rebootRequired": configured_route != active_route}


def route_action(action: str, manifest_path: pathlib.Path, route: str | None) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    if route is not None and manifest.get("route") != route: raise Failure("requested route differs from development manifest")
    if action in {"status", "verify"}:
        state = route_observation(manifest_path)
        if action == "verify" and any((state["configuredRoute"] not in {None, manifest.get("route")},
                                       state["overlayActiveRoute"] not in {None, manifest.get("route")},
                                       state["moduleReportedRoute"] not in {None, manifest.get("route")})):
            raise Failure("development route identity mismatch")
        return state
    require_root(); selected = route or manifest.get("route")
    if selected not in ROUTES: raise Failure("an explicit gpio4 or gpio20 route is required")
    kernel = manifest.get("targetKernel") or platform.release(); print_mutation_identity(kernel)
    config = root_path("/boot/firmware/config.txt")
    if config.is_symlink() or not config.is_file(): raise Failure("boot configuration is absent or unsafe")
    record_path = root_path(STATE_BASE / f"route-{manifest['sourceCommit'][:12]}-{selected}.json")
    if action == "rollback":
        try: record = json.loads(record_path.read_text())
        except (OSError,json.JSONDecodeError) as error: raise Failure(f"route rollback record unavailable: {error}") from error
        if record.get("schema") != ROLLBACK_SCHEMA or record.get("kind") != "development-route": raise Failure("invalid development route record")
        lines=[line for line in config.read_text().splitlines() if line != f"dtoverlay={ROUTES[selected]}"]
        atomic_write(config,("\n".join(lines)+"\n").encode(),stat.S_IMODE(config.stat().st_mode))
        record["status"]="removed-awaiting-reboot"; atomic_write(record_path,canonical(record))
        return {"status":"removed-awaiting-reboot","affectedFile":str(config),"rebootRequired":True}
    before = config.read_bytes(); text = before.decode(errors="strict")
    lines = [line for line in text.splitlines() if not any(line == f"dtoverlay={overlay}" for overlay in ROUTES.values())]
    lines.append(f"dtoverlay={ROUTES[selected]}")
    after = ("\n".join(lines) + "\n").encode()
    record = {"schema": ROLLBACK_SCHEMA, "kind": "development-route", "manifest": str(manifest_path),
              "path": str(config), "beforeSha256": sha256_bytes(before), "before": before.decode(),
              "afterSha256": sha256_bytes(after), "route": selected, "status": "prepared",
              "rollbackCommand": f"sudo ./scripts/development-route rollback --manifest {manifest_path}"}
    atomic_write(record_path, canonical(record)); atomic_write(config, after, stat.S_IMODE(config.stat().st_mode))
    record["status"] = "awaiting-reboot"; atomic_write(record_path, canonical(record))
    return {**route_observation(manifest_path), "affectedFiles": [str(config), str(record_path)],
            "priorSha256": record["beforeSha256"], "newSha256": record["afterSha256"],
            "ownership": "development-recorded-exact-file", "rollbackCommand": record["rollbackCommand"]}


def overlay_action(action: str, manifest_path: pathlib.Path, output: pathlib.Path | None) -> dict[str, Any]:
    manifest = load_manifest(manifest_path); tree = pathlib.Path(manifest["renderedTree"]); route = manifest.get("route")
    if route not in ROUTES: raise Failure("manifest route is absent")
    kernel = manifest.get("targetKernel") or platform.release()
    if action == "status": return route_observation(manifest_path)
    require_root(); print_mutation_identity(kernel)
    record = root_path(STATE_BASE / f"overlay-{manifest['sourceCommit'][:12]}-{route}.json")
    if action == "rollback":
        try: payload=json.loads(record.read_text())
        except (OSError,json.JSONDecodeError) as error: raise Failure(f"overlay rollback record unavailable: {error}") from error
        destination=pathlib.Path(payload["path"])
        if payload.get("schema")!=ROLLBACK_SCHEMA or payload.get("kind")!="development-overlay": raise Failure("invalid development overlay record")
        if destination.is_file(): destination.unlink()
        payload["status"]="removed"; atomic_write(record,canonical(payload))
        return {"status":"removed","affectedFile":str(destination),"rebootRequired":True}
    tools = tool_inventory(); dtc, cpp = tools["dtc"], tools["cpp"]
    if not dtc or not cpp: raise Failure("overlay build requires cpp and dtc")
    output = (output or pathlib.Path(manifest["renderedTree"]) / "development-overlays").absolute()
    output.mkdir(parents=True, exist_ok=True)
    common = root_path(f"/usr/src/linux-headers-{kernel.replace('+rpt-rpi-2712','+rpt-common-rpi')}/include")
    if not common.is_dir(): raise Failure(f"device-tree headers unavailable: {common}")
    source = tree / "overlays" / f"rp1-gpclk-{route}.dts"; pp = output / f"rp1-gpclk-{route}.pp.dts"; artifact = output / f"rp1-gpclk-{route}.dtbo"
    pre = run([cpp, "-nostdinc", "-I", str(common), "-undef", "-x", "assembler-with-cpp", str(source)])
    atomic_write(pp, (pre.stdout or "").encode(), 0o644)
    run([dtc, "-@", "-I", "dts", "-O", "dtb", "-o", str(artifact), str(pp)])
    result = {"route": route, "source": str(source), "sourceSha256": sha256(source), "artifact": str(artifact), "artifactSha256": sha256(artifact)}
    if action == "install":
        destination = root_path(f"/boot/firmware/overlays/rp1-gpclk-{route}.dtbo")
        before = {"present": destination.is_file(), "sha256": sha256(destination) if destination.is_file() else None}
        if destination.exists() and (destination.is_symlink() or not destination.is_file()): raise Failure("overlay destination is unsafe")
        payload = {"schema": ROLLBACK_SCHEMA, "kind": "development-overlay", "path": str(destination), "before": before,
                   "newSha256": result["artifactSha256"], "manifest": str(manifest_path), "status": "prepared"}
        atomic_write(record, canonical(payload)); shutil.copyfile(artifact, destination); destination.chmod(0o644)
        payload["status"] = "installed"; atomic_write(record, canonical(payload)); result.update(installedPath=str(destination), prior=before,
            rebootRequired=True, rollbackRecord=str(record))
    update_manifest(manifest_path, {"overlayIdentity": result})
    return result


def parser_for(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"scripts/{command}")
    if command == "render-development-tree":
        parser.add_argument("--source", required=True); parser.add_argument("--output", required=True)
        parser.add_argument("--allow-dirty", action="store_true")
        parser.add_argument("--runtime-controller", action="store_true")
    elif command == "development-preflight":
        parser.add_argument("--source", default="."); parser.add_argument("--kernel", default=platform.release())
    elif command == "development-install":
        parser.add_argument("--source", default="."); parser.add_argument("--kernel", default=platform.release())
        route = parser.add_mutually_exclusive_group(required=True)
        route.add_argument("--route", choices=ROUTES)
        route.add_argument("--route-neutral", action="store_true")
        parser.add_argument("--output-inhibit", type=int, choices=(0,1), required=True); parser.add_argument("--evidence-directory", required=True)
        parser.add_argument("--build-only", action="store_true"); parser.add_argument("--install", action="store_true")
        parser.add_argument("--load", action="store_true")
        parser.add_argument("--keep-build", action="store_true"); parser.add_argument("--allow-dirty", action="store_true")
        parser.add_argument("--runtime-controller", action="store_true")
    elif command == "development-enroll":
        parser.add_argument("--manifest", type=pathlib.Path, required=True); parser.add_argument("--route", choices=ROUTES, required=True)
        parser.add_argument("--kernel", required=True); parser.add_argument("--remove", action="store_true")
    elif command == "development-module":
        parser.add_argument("action", choices=("load","reload","status","unload")); parser.add_argument("--manifest", type=pathlib.Path, required=True)
        parser.add_argument("--output-inhibit", type=int, choices=(0,1), default=1)
    elif command in {"development-status", "development-endpoint"}:
        parser.add_argument("--manifest", type=pathlib.Path, required=True); parser.add_argument("--json", action="store_true")
    elif command == "development-rollback": parser.add_argument("--record", type=pathlib.Path, required=True)
    elif command == "development-route":
        parser.add_argument("action", choices=("status","apply","verify","rollback")); parser.add_argument("--development-manifest", "--manifest", dest="manifest", type=pathlib.Path, required=True)
        parser.add_argument("--route", choices=ROUTES)
    elif command == "development-overlay":
        parser.add_argument("action", choices=("build","install","status","rollback")); parser.add_argument("--manifest", type=pathlib.Path, required=True)
        parser.add_argument("--output", type=pathlib.Path)
    return parser


def main() -> int:
    command = pathlib.Path(sys.argv[0]).name
    if command == "development_workflow.py":
        if len(sys.argv) < 2: raise Failure("development command required")
        command, sys.argv = sys.argv[1], [sys.argv[0], *sys.argv[2:]]
    args = parser_for(command).parse_args()
    if command == "render-development-tree": result = {"manifest": str(render(
        pathlib.Path(args.source), pathlib.Path(args.output), args.allow_dirty,
        args.runtime_controller))}
    elif command == "development-preflight":
        source = pathlib.Path(args.source).resolve()
        result = {"classification":"source-development", "kernels":kernel_identities(args.kernel),
                  "tools":tool_inventory(), "moduleName":CANONICAL_MODULE,
                  "moduleVersion":canonical_module_version(source),
                  "versionSource":"include/rp1_gpclk/version.h",
                  "versionSourceSha256":sha256(source / "include/rp1_gpclk/version.h")}
    elif command == "development-install": result = install(args)
    elif command == "development-enroll": result = enroll(args.manifest, args.route, args.kernel, args.remove)
    elif command == "development-module": result = lifecycle_action(args.action, args.manifest, args.output_inhibit)
    elif command == "development-status": result = lifecycle_status(args.manifest)
    elif command == "development-endpoint": result = lifecycle_status(args.manifest)["endpoint"]
    elif command == "development-rollback": result = rollback(args.record)
    elif command == "development-route": result = route_action(args.action, args.manifest, args.route)
    elif command == "development-overlay": result = overlay_action(args.action, args.manifest, args.output)
    else: raise Failure(f"unknown development command: {command}")
    sys.stdout.buffer.write(canonical(result)); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except (Failure, OSError, subprocess.SubprocessError) as error:
        print(f"development workflow failed: {error}", file=sys.stderr); raise SystemExit(2)
