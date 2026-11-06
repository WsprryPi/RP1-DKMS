#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free source-development workflow contract tests."""

import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
import bz2, gzip, importlib.util, json, lzma, os, pathlib, platform, re, shutil, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("development_workflow", ROOT / "scripts/development_workflow.py")
DEV = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(DEV)


def command(*args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def fixture_repo(base: pathlib.Path) -> pathlib.Path:
    source = base / "source"; shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    command("git", "init", "-q", cwd=source); command("git", "config", "user.email", "test@example.invalid", cwd=source)
    command("git", "config", "user.name", "test", cwd=source); command("git", "add", ".", cwd=source)
    assert command("git", "commit", "-qm", "fixture", cwd=source).returncode == 0
    assert command("git", "remote", "add", "origin", "https://github.com/WsprryPi/RP1-GPIO-CLK-DKMS.git", cwd=source).returncode == 0
    return source


def test_render() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary); source = fixture_repo(base); output = base / "rendered"
        result = command(str(source / "scripts/render-development-tree"), "--source", str(source), "--output", str(output), cwd=source)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((output / "DEVELOPMENT_MANIFEST.json").read_text())
        assert manifest["schema"] == DEV.SCHEMA == "rp1-gpclk-source-development-manifest"
        workflow = (source / ".github/workflows/offline.yml").read_text()
        schema_references = set(re.findall(r"\bschema/[A-Za-z0-9_.-]+\.schema\.json\b", workflow))
        expected_schema = f"schema/{manifest['schema']}.schema.json"
        tracked = set(command("git", "ls-files", cwd=source).stdout.splitlines())
        assert expected_schema in schema_references
        assert all((source / reference).is_file() and reference in tracked
                   for reference in schema_references)
        assert manifest["classification"] == "source-development" and manifest["qualification"] is False
        assert manifest["moduleName"] == "rp1_gpclk_dkms"
        assert manifest["versionIdentity"]["moduleVersion"] == VERSION
        assert manifest["versionIdentity"]["path"] == "include/rp1_gpclk/version.h"
        assert manifest["versionIdentity"]["sha256"] == DEV.sha256(output / "include/rp1_gpclk/version.h")
        assert [item["operation"] for item in manifest["transformations"]] == ["replace-module-version-placeholder","relax-development-kernel-name-filter"]
        assert manifest["changedFiles"] == ["dkms.conf"]
        assert ('PACKAGE_VERSION="' + VERSION + '"') in (output / "dkms.conf").read_text()
        assert 'BUILD_EXCLUSIVE_KERNEL=".*"' in (output / "dkms.conf").read_text()
        assert 'PACKAGE_VERSION="#MODULE_VERSION#"' not in (output / "dkms.conf").read_text()
        assert not (source / "DEVELOPMENT_MANIFEST.json").exists()
        again = command(str(source / "scripts/render-development-tree"), "--source", str(source), "--output", str(output), cwd=source)
        assert again.returncode == 2 and "already exists" in again.stderr
        (source / "README.md").write_text((source / "README.md").read_text() + "\ndirty\n")
        rejected = command(str(source / "scripts/render-development-tree"), "--source", str(source), "--output", str(base / "dirty"), cwd=source)
        assert rejected.returncode == 2 and "dirty" in rejected.stderr
        allowed = command(str(source / "scripts/render-development-tree"), "--source", str(source), "--output", str(base / "allowed"), "--allow-dirty", cwd=source)
        assert allowed.returncode == 0 and json.loads((base / "allowed/DEVELOPMENT_MANIFEST.json").read_text())["sourceState"] == "dirty-explicitly-allowed"


def test_runtime_controller_render() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary); source = fixture_repo(base); output = base / "runtime-rendered"
        result = command(str(source / "scripts/render-development-tree"), "--source", str(source),
                         "--output", str(output), "--runtime-controller", cwd=source)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((output / "DEVELOPMENT_MANIFEST.json").read_text())
        configuration = (output / "dkms.conf").read_text()
        assert manifest["buildProfile"] == "runtime-controller"
        assert [item["operation"] for item in manifest["transformations"]] == [
            "replace-module-version-placeholder", "relax-development-kernel-name-filter",
            "select-runtime-controller-profile"]
        assert "RP1_RUNTIME_CONTROLLER=1" in configuration
        assert 'BUILT_MODULE_NAME[1]="rp1_route_controller"' in configuration
        assert 'AUTOINSTALL="no"' in configuration


def test_forbidden_transform() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary); source = fixture_repo(base)
        (source / "README.md").write_text((source / "README.md").read_text() + '\nPACKAGE_VERSION="#OTHER_VERSION#"\n')
        command("git", "add", "README.md", cwd=source); command("git", "commit", "-qm", "forbidden", cwd=source)
        result = command(str(source / "scripts/render-development-tree"), "--source", str(source), "--output", str(base / "output"), cwd=source)
        assert result.returncode == 2 and "unresolved" in result.stderr and not (base / "output").exists()


def test_compression() -> None:
    elf = b"\x7fELF" + bytes(range(256))
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary)
        variants = {"module.ko": elf, "module.ko.xz": lzma.compress(elf), "module.ko.gz": gzip.compress(elf), "module.ko.bz2": bz2.compress(elf)}
        for name, payload in variants.items():
            path = base / name; path.write_bytes(payload)
            assert DEV.decompressed(path) == elf
            assert DEV.sha256_bytes(DEV.decompressed(path)) == DEV.sha256_bytes(elf)
    assert DEV.CANONICAL_MODULE == "rp1_gpclk_dkms" and DEV.CANONICAL_MODULE != "rp1_gpclk"


def test_false_qualification_and_cli() -> None:
    source = (ROOT / "scripts/development_workflow.py").read_text()
    assert '"releaseQualified": False' in source and '"classification": "Experimental"' in source
    preflight = command(str(ROOT / "scripts/development-preflight"), "--source", str(ROOT))
    identity = json.loads(preflight.stdout)
    assert identity["moduleVersion"] == VERSION
    assert identity["versionSource"] == "include/rp1_gpclk/version.h"
    assert identity["versionSourceSha256"] == DEV.sha256(ROOT / identity["versionSource"])
    for script in ("development-preflight", "development-install", "development-enroll", "development-module",
                   "development-status", "development-endpoint", "development-route", "development-overlay", "development-rollback"):
        result = command(str(ROOT / "scripts" / script), "--help")
        assert result.returncode == 0, (script, result.stderr)
        if script == "development-install":
            assert "--route-neutral" in result.stdout


def executable(path: pathlib.Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body); path.chmod(0o755)


def test_controlled_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base=pathlib.Path(temporary); source=fixture_repo(base); fake_root=base/"root"; tools=base/"tools"; tools.mkdir()
        kernel=platform.release(); (fake_root/f"lib/modules/{kernel}/build").mkdir(parents=True)
        executable(tools/"dkms", ('\ncase "$1" in\n install) mkdir -p "$RP1_GPCLK_DEVELOPMENT_ROOT/lib/modules/$7/updates/dkms"; printf \'\\177ELFfake-development-module\' >"$RP1_GPCLK_DEVELOPMENT_ROOT/lib/modules/$7/updates/dkms/rp1_gpclk_dkms.ko" ;;\n remove) rm -f "$RP1_GPCLK_DEVELOPMENT_ROOT/lib/modules/$RP1_TEST_KERNEL/updates/dkms/rp1_gpclk_dkms.ko" ;;\n status) [ -d "$RP1_GPCLK_DEVELOPMENT_ROOT/usr/src/rp1-gpclk-dkms-' + VERSION + '" ] || exit 0; printf \'rp1-gpclk-dkms/' + VERSION + ', %s, installed\\n\' "$RP1_TEST_KERNEL" ;;\nesac\n'))
        executable(tools/"modinfo", ('\nfield=$2\ncase "$field" in name) echo rp1_gpclk_dkms;; version) echo ' + VERSION + ';; vermagic) echo "$RP1_TEST_KERNEL SMP mod_unload aarch64";; signer|sig_key|sig_hashalgo) :;; esac\n'))
        executable(tools/"depmod", ":\n")
        executable(tools/"modprobe", ('\nif [ "${1:-}" = -r ]; then rm -rf "$RP1_GPCLK_DEVELOPMENT_ROOT/sys/module/rp1_gpclk_dkms"; exit 0; fi\nmkdir -p "$RP1_GPCLK_DEVELOPMENT_ROOT/sys/module/rp1_gpclk_dkms/parameters"\necho ' + VERSION + ' >"$RP1_GPCLK_DEVELOPMENT_ROOT/sys/module/rp1_gpclk_dkms/version"\ncase "$2" in output_inhibit=1) echo Y;; *) echo N;; esac >"$RP1_GPCLK_DEVELOPMENT_ROOT/sys/module/rp1_gpclk_dkms/parameters/output_inhibit"\n'))
        environment={**os.environ,"RP1_GPCLK_DEVELOPMENT_ROOT":str(fake_root),"RP1_GPCLK_DEVELOPMENT_TEST_ROOT":"1","RP1_TEST_KERNEL":kernel,
            "RP1_GPCLK_TOOL_DKMS":str(tools/"dkms"),"RP1_GPCLK_TOOL_MODINFO":str(tools/"modinfo"),
            "RP1_GPCLK_TOOL_DEPMOD":str(tools/"depmod"),"RP1_GPCLK_TOOL_MODPROBE":str(tools/"modprobe")}

        def neutral(name, *extra):
            return command(str(source/"scripts/development-install"), "--source", str(source), "--kernel", kernel,
                "--route-neutral", "--output-inhibit", "1", "--install",
                "--evidence-directory", str(base/name), *extra, cwd=source, env=environment)

        capable = command(str(source/"scripts/development-install"), "--source", str(source), "--kernel", kernel,
            "--route-neutral", "--output-inhibit", "0", "--install",
            "--evidence-directory", str(base/"neutral-capable"), cwd=source, env=environment)
        assert capable.returncode == 2 and "output_inhibit=1" in capable.stderr and not (base/"neutral-capable").exists()
        loaded = neutral("neutral-load", "--load")
        assert loaded.returncode == 2 and "cannot load" in loaded.stderr and not (base/"neutral-load").exists()
        both = command(str(source/"scripts/development-install"), "--source", str(source), "--kernel", kernel,
            "--route-neutral", "--route", "gpio4", "--output-inhibit", "1",
            "--evidence-directory", str(base/"neutral-both"), cwd=source, env=environment)
        assert both.returncode == 2 and not (base/"neutral-both").exists()

        config = fake_root/"boot/firmware/config.txt"; config.parent.mkdir(parents=True); config.write_text("dtoverlay=rp1-gpclk-gpio4\n")
        blocked = neutral("neutral-configured")
        assert blocked.returncode == 2 and "configuredRoutes" in blocked.stderr and not (base/"neutral-configured").exists()
        config.unlink()
        overlay = fake_root/"boot/firmware/overlays/rp1-gpclk-gpio20.dtbo"; overlay.parent.mkdir(parents=True); overlay.write_bytes(b"overlay")
        blocked = neutral("neutral-overlay")
        assert blocked.returncode == 2 and "routeOverlayFiles" in blocked.stderr and not (base/"neutral-overlay").exists()
        overlay.unlink()
        installed_overlay = fake_root/"usr/lib/rp1-gpclk-dkms/overlays/rp1-gpclk-gpio4.dtbo"
        installed_overlay.parent.mkdir(parents=True); installed_overlay.write_bytes(b"overlay")
        blocked = neutral("neutral-installed-overlay")
        assert blocked.returncode == 2 and "routeOverlayFiles" in blocked.stderr and not (base/"neutral-installed-overlay").exists()
        installed_overlay.unlink()
        node = fake_root/"sys/firmware/devicetree/base/rp1-gpclk-dkms-gpio4"; node.mkdir(parents=True)
        blocked = neutral("neutral-active")
        assert blocked.returncode == 2 and "activeRoutes" in blocked.stderr and not (base/"neutral-active").exists()
        node.rmdir()
        endpoint = fake_root/"dev/rp1-gpclk"; endpoint.parent.mkdir(parents=True); endpoint.write_text("")
        blocked = neutral("neutral-endpoint")
        assert blocked.returncode == 2 and "endpointPresent" in blocked.stderr and not (base/"neutral-endpoint").exists()
        endpoint.unlink()
        loaded_path = fake_root/"sys/module/rp1_gpclk_dkms"; loaded_path.mkdir(parents=True)
        blocked = neutral("neutral-loaded")
        assert blocked.returncode == 2 and "loadedModule" in blocked.stderr and not (base/"neutral-loaded").exists()
        loaded_path.rmdir()
        controller = fake_root/"sys/module/rp1_route_controller"; controller.mkdir(parents=True)
        blocked = neutral("neutral-controller")
        assert blocked.returncode == 2 and "loadedRouteController" in blocked.stderr and not (base/"neutral-controller").exists()
        controller.rmdir()
        legacy_endpoint = fake_root/"dev/rp1-gpclk0"; legacy_endpoint.write_text("")
        blocked = neutral("neutral-legacy-endpoint")
        assert blocked.returncode == 2 and "historicalEndpointPresent" in blocked.stderr and not (base/"neutral-legacy-endpoint").exists()
        legacy_endpoint.unlink()
        controller_endpoint = fake_root/"dev/rp1-route-admin"; controller_endpoint.write_text("")
        blocked = neutral("neutral-controller-endpoint")
        assert blocked.returncode == 2 and "routeControllerEndpointPresent" in blocked.stderr and not (base/"neutral-controller-endpoint").exists()
        controller_endpoint.unlink()
        predecessor_node = fake_root/"sys/firmware/devicetree/base/rp1-gpclk-dkms"; predecessor_node.mkdir(parents=True)
        blocked = neutral("neutral-predecessor-node")
        assert blocked.returncode == 2 and "activeRoutes" in blocked.stderr and not (base/"neutral-predecessor-node").exists()
        predecessor_node.rmdir()

        neutral_evidence = base/"neutral-evidence"
        neutral_result = neutral("neutral-evidence")
        assert neutral_result.returncode == 0, neutral_result.stderr
        neutral_manifest = json.loads((neutral_evidence/"rendered-source/DEVELOPMENT_MANIFEST.json").read_text())
        assert neutral_manifest["route"] is None and neutral_manifest["installationMode"] == "route-neutral"
        assert neutral_manifest["parameters"]["output_inhibit"] == 1
        assert neutral_manifest["installedModule"]["kernel"] == kernel
        assert neutral_manifest["routeNeutralSafety"] == {
            "before": {"activeRoutes": [], "configuredRoutes": [], "endpointPresent": False,
                       "historicalEndpointPresent": False, "loadedModule": False,
                       "loadedRouteController": False, "routeControllerEndpointPresent": False,
                       "routeOverlayFiles": []},
            "after": {"activeRoutes": [], "configuredRoutes": [], "endpointPresent": False,
                      "historicalEndpointPresent": False, "loadedModule": False,
                      "loadedRouteController": False, "routeControllerEndpointPresent": False,
                      "routeOverlayFiles": []},
        }
        assert json.loads((neutral_evidence/"RESULT.json").read_text())["state"] == "development-installed"
        assert not (fake_root/"sys/module/rp1_gpclk_dkms").exists()

        repeat = neutral("neutral-repeat")
        assert repeat.returncode == 0, repeat.stderr
        repeated = json.loads(repeat.stdout)
        assert repeated["unchanged"] is True
        assert repeated["rollback"] == str(neutral_evidence/"ROLLBACK.json")
        assert not (base/"neutral-repeat/dkms-build.log").exists()

        evidence=base/"evidence"
        result=command(str(source/"scripts/development-install"),"--source",str(source),"--kernel",kernel,"--route","gpio4","--output-inhibit","1","--load","--evidence-directory",str(evidence),cwd=source,env=environment)
        assert result.returncode==0,result.stderr
        manifest=evidence/"rendered-source/DEVELOPMENT_MANIFEST.json"; value=json.loads(manifest.read_text())
        assert value["developmentState"]=="development-output-inhibited" and value["installedModule"]["moduleName"]=="rp1_gpclk_dkms"
        replacement=base/"replacement-evidence"
        replaced=command(str(source/"scripts/development-install"),"--source",str(source),"--kernel",kernel,"--route","gpio4","--output-inhibit","1","--load","--evidence-directory",str(replacement),cwd=source,env=environment)
        assert replaced.returncode==0,replaced.stderr
        assert (replacement/"dkms-remove.log").is_file() and (replacement/"module-unload-for-replace.log").is_file()
        backup = json.loads((replacement/"ROLLBACK.json").read_text())
        assert (pathlib.Path(backup["priorSource"])/"DEVELOPMENT_MANIFEST.json").is_file()
        for item in backup["prior"]["installedArtifacts"]:
            assert DEV.sha256(pathlib.Path(item["backup"])) == item["sha256"]
        stale=command(str(source/"scripts/development-rollback"),"--record",str(evidence/"ROLLBACK.json"),env=environment)
        assert stale.returncode==2 and "another instance" in stale.stderr
        assert (fake_root/"sys/module/rp1_gpclk_dkms").exists()
        manifest=replacement/"rendered-source/DEVELOPMENT_MANIFEST.json"
        assert (replacement.stat().st_mode & 0o777)==0o755
        status=command(str(source/"scripts/development-status"),"--manifest",str(manifest),"--json",env=environment)
        assert status.returncode==0 and json.loads(status.stdout)["developmentState"]=="development-output-inhibited"
        enrolled=command(str(source/"scripts/development-enroll"),"--manifest",str(manifest),"--route","gpio4","--kernel",kernel,env=environment)
        assert enrolled.returncode==0,enrolled.stderr
        enrollment=json.loads(enrolled.stdout)
        assert enrollment["record"]["moduleVersion"]==VERSION and enrollment["record"]["qualification"] is False
        removed=command(str(source/"scripts/development-enroll"),"--remove","--manifest",str(manifest),"--route","gpio4","--kernel",kernel,env=environment)
        assert removed.returncode==0,removed.stderr
        unloaded=command(str(source/"scripts/development-module"),"unload","--manifest",str(manifest),env=environment)
        assert unloaded.returncode==0,unloaded.stderr
        rolled=command(str(source/"scripts/development-rollback"),"--record",str(replacement/"ROLLBACK.json"),env=environment)
        assert rolled.returncode==0,rolled.stderr
        assert not (fake_root/f"usr/src/rp1-gpclk-dkms-{VERSION}").exists()


def main() -> None:
    test_render(); test_runtime_controller_render(); test_forbidden_transform(); test_compression(); test_false_qualification_and_cli(); test_controlled_lifecycle()
    print("development workflow checks passed")


if __name__ == "__main__": main()
