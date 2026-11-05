#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free checks for the passive source-development route-manager lifecycle."""
import importlib.util, json, os, pathlib, shutil, subprocess, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("development_route_manager",ROOT/"scripts/development_route_manager.py")
DEV=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(DEV)

def executable(path:pathlib.Path,body:str)->None:
    path.write_text("#!/bin/sh\nset -eu\n"+body); path.chmod(0o755)

with tempfile.TemporaryDirectory() as temporary:
    base=pathlib.Path(temporary); fake=base/"root"; source=base/"source"; tools=base/"tools"; tools.mkdir()
    shutil.copytree(ROOT,source,ignore=shutil.ignore_patterns(".git","__pycache__"))
    subprocess.run(["git","init","-q"],cwd=source,check=True); subprocess.run(["git","config","user.email","test@example.invalid"],cwd=source,check=True)
    subprocess.run(["git","config","user.name","test"],cwd=source,check=True); subprocess.run(["git","add","."],cwd=source,check=True)
    subprocess.run(["git","commit","-qm","fixture"],cwd=source,check=True)
    commit=subprocess.run(["git","rev-parse","HEAD"],cwd=source,text=True,stdout=subprocess.PIPE,check=True).stdout.strip()
    for name in DEV.PACKAGE_PATHS:
        path=fake/name.lstrip("/"); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(name+"\n"); path.chmod(0o755 if "/usr/sbin/" in name or "/libexec/" in name else 0o644)
    inhibit=fake/"sys/module/rp1_gpclk_dkms/parameters/output_inhibit"; inhibit.parent.mkdir(parents=True); inhibit.write_text("Y\n")
    (fake/"sys/module/rp1_gpclk_dkms/refcnt").write_text("0\n")
    boot=fake/"proc/sys/kernel/random/boot_id"; boot.parent.mkdir(parents=True); boot.write_text("11111111-2222-3333-4444-555555555555\n")
    config=fake/"boot/firmware/config.txt"; config.parent.mkdir(parents=True); config.write_text("fixture gpio4 config\n")
    state=base/"systemd.json"; state.write_text(json.dumps({"dropin":"","exec":"/usr/sbin/rp1-gpclk-route-manager"}))
    executable(tools/"systemctl",r'''state="$RP1_TEST_SYSTEMD_STATE"
case "$1:${2:-}" in
 is-active:wsprrypi.service) echo inactive; exit 3;;
 show:-p)
   value=$(cat "$state")
   case "$3" in FragmentPath) echo /usr/lib/systemd/system/rp1-gpclk-route-manager@.service;; DropInPaths) python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dropin"])' "$state";; ExecStart) python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["exec"])' "$state";; esac;;
 daemon-reload:) :;;
 restart:rp1-gpclk-route-manager.socket)
   drop="$RP1_GPCLK_DEVELOPMENT_ROOT/etc/systemd/system/rp1-gpclk-route-manager@.service.d/90-source-development.conf"
   if [ -f "$drop" ]; then execpath=$(sed -n 's/^ExecStart=\(\/.*\)$/\1/p' "$drop"); python3 -c 'import json,sys; json.dump({"dropin":sys.argv[2],"exec":sys.argv[3]},open(sys.argv[1],"w"))' "$state" "$drop" "$execpath"; else echo '{"dropin":"","exec":"/usr/sbin/rp1-gpclk-route-manager"}' >"$state"; fi;;
 *) echo "unexpected systemctl: $*" >&2; exit 2;;
esac
''')
    manifest=base/"module-manifest.json"; manifest.write_text(json.dumps({"schema":DEV.MANIFEST_SCHEMA,"classification":"source-development","qualification":False,"sourceState":"clean","sourceCommit":"7"*40,"targetKernel":"fixture-kernel","route":"gpio4","renderedVersion":"0.99.0","uapiIdentity":{"sha256":"4af14cdf60471ac4b318b10d7d70824a63c74029c2934e86bbdcd1b7f06cf633"}}))
    old=dict(os.environ); os.environ.update({"RP1_GPCLK_DEVELOPMENT_ROOT":str(fake),"RP1_GPCLK_DEVELOPMENT_TEST_ROOT":"1","RP1_GPCLK_TOOL_SYSTEMCTL":str(tools/"systemctl"),"RP1_TEST_SYSTEMD_STATE":str(state)})
    try:
        args=type("Args",(),{"source":source,"module_manifest":manifest,"route":"gpio4","kernel":"fixture-kernel"})()
        installed=DEV.install(args); assert installed["status"]=="deployed-awaiting-current-boot-adoption" and installed["sourceCommit"]==commit
        status_args=type("Args",(),{"record":DEV.root(DEV.RECORD)})(); package_before=DEV.package_inventory()
        try: DEV.status(status_args)
        except DEV.Failure: pass
        else: raise AssertionError("deployment without adoption reported ready")
        binding=DEV.load(DEV.root(f"{DEV.BASE}/{commit}/binding.json"))
        safety={"endpointOwned":True,"endpointOpen":False,"outputInhibited":True,"services":{}}
        DEV.passive_query=lambda:{"status":"ok","state":{"bootOwnership":"unadopted-source-development","configuredRoute":"gpio4","activeRoute":"gpio4","pendingTransaction":None,"bootId":boot.read_text().strip(),"configSha256":DEV.digest(config),"safety":safety}}
        adopted=DEV.adopt(status_args); assert adopted["status"]=="ok" and adopted["passiveQuery"] is None
        assert DEV.status(status_args)==adopted
        altered=dict(binding); altered["route"]="gpio20"
        binding_path=DEV.root(f"{DEV.BASE}/{commit}/binding.json"); binding_path.write_bytes(DEV.canonical(altered))
        try: DEV.status(type("Args",(),{"record":DEV.root(DEV.RECORD)})())
        except DEV.Failure: pass
        else: raise AssertionError("altered binding accepted")
        binding_path.write_bytes(DEV.canonical(json.loads(DEV.root(DEV.RECORD).read_text())["binding"]))
        boot.write_text("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n")
        try: DEV.status(status_args)
        except DEV.Failure: pass
        else: raise AssertionError("stale boot adoption accepted")
        boot.write_text("11111111-2222-3333-4444-555555555555\n")
        assert DEV.rollback_adoption(status_args)["status"]=="adoption-rolled-back"
        try: DEV.status(status_args)
        except DEV.Failure: pass
        else: raise AssertionError("removed adoption reported ready")
        original_status=DEV.status; DEV.status=lambda unused:(_ for _ in ()).throw(DEV.Failure("injected readiness race"))
        try: DEV.adopt(status_args)
        except DEV.Failure: pass
        else: raise AssertionError("failed adoption readiness was accepted")
        finally: DEV.status=original_status
        assert not DEV.paths(commit)["adoption"].exists()
        DEV.adopt(status_args)
        unrelated=fake/"etc/systemd/system/unrelated.service"; unrelated.parent.mkdir(parents=True,exist_ok=True); unrelated.write_text("preserve\n")
        rolled=DEV.rollback(type("Args",(),{"record":DEV.root(DEV.RECORD)})()); assert rolled["status"]=="rolled-back"
        assert unrelated.read_text()=="preserve\n" and DEV.package_inventory()==package_before and not DEV.root(DEV.DROPIN).exists()
        assert json.loads(state.read_text())["exec"]=="/usr/sbin/rp1-gpclk-route-manager"
        reinstalled=DEV.install(args); successor=DEV.load(DEV.root(DEV.RECORD)); predecessor=successor["predecessorRollbackRecord"]
        assert reinstalled["status"]=="deployed-awaiting-current-boot-adoption"
        assert predecessor["sourceCommit"]==commit and pathlib.Path(predecessor["path"]).is_file()
        assert DEV.digest(pathlib.Path(predecessor["path"]))==predecessor["sha256"]
        DEV.rollback(status_args)
        DEV.root(DEV.RECORD).write_text("{}\n")
        try: DEV.install(args)
        except DEV.Failure: pass
        else: raise AssertionError("malformed predecessor record accepted")
        (source/"README.md").write_text((source/"README.md").read_text()+"dirty\n")
        try: DEV.clean_source(source)
        except DEV.Failure: pass
        else: raise AssertionError("dirty source accepted")
    finally:
        os.environ.clear(); os.environ.update(old)

source=(ROOT/"scripts/development_route_manager.py").read_text()
assert "client.shutdown(socket.SHUT_WR)" in source
for forbidden in ("modprobe ","/dev/mem","Soapy","transmit"):
    assert forbidden not in source
print("source-development route manager lifecycle: PASS")
