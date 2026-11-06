#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic offline checks for the diagnostics contract."""

from __future__ import annotations
import sys as _identity_sys
from pathlib import Path as _IdentityPath
_identity_sys.path.insert(0, str(_IdentityPath(__file__).resolve().parents[1]/'scripts'))
from version_identity import VERSION, DEBIAN, COMPATIBILITY, expand
import importlib.util, json, pathlib, struct, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("diagnostics",ROOT/"scripts/rp1-gpclk-diagnostics.py")
module=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(module)
contract=json.loads((ROOT/"release/diagnostics-contract-v1.json").read_text())
assert contract["readOnly"] is True and len(contract["categories"])==6
assert {"module-load","overlay-apply","gpio-write","repair","rf"} <= set(contract["prohibitedActions"])

def write(root: pathlib.Path, name: str, value):
    path=root/name.lstrip("/"); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value,(dict,list)) else value)

commands=[]
def runner(args):
    commands.append(args)
    assert args[0] in {"dpkg-query","dkms","modinfo","journalctl"}
    if args[0]=="journalctl": assert args[1:5]==["-k","-b","--no-pager","-g"]
    return {"status":"ok","exitStatus":0,"stdout":"fixture\n","stderr":"","truncated":False}

with tempfile.TemporaryDirectory() as temporary:
    root=pathlib.Path(temporary); kernel="6.18.34+rpt-rpi-2712"
    (root/f"lib/modules/{kernel}/build").mkdir(parents=True)
    write(root,f"/lib/modules/{kernel}/updates/dkms/{module.MODULE}.ko","module")
    write(root,"/proc/device-tree/model","Raspberry Pi 5 Model B")
    write(root,"/sys/module/rp1_gpclk_dkms/parameters/output_inhibit","0")
    write(root,"/var/lib/rp1-gpclk-dkms/transaction.json",{"status":"complete","ownedFiles":[],"ownedDirectories":[]})
    query={"status":"ok","route":"GPIO4","compatibilityState":"Compatible-unqualified",
           "compatibilityReason":"identity-unknown","compatibilityId":"entry","capabilities":["route-identity","submit-events"],"cleanupFault":False}
    write(root,"/run/rp1-gpclk-dkms/query-fixture.json",query)
    snapshot={"status":"ok","route":"GPIO4","operationState":"IDLE",
              "stable":"true","nonOwning":True,"leaseTokenExposed":False,"descriptorClosed":True}
    write(root,"/run/rp1-gpclk-dkms/passive-snapshot-fixture.json",snapshot)
    endpoint=root/"sys/firmware/devicetree/base/axi/rp1/rp1-gpclk-dkms-gpio4"; endpoint.mkdir(parents=True)
    write(root,"/sys/firmware/devicetree/base/axi/rp1/rp1-gpclk-dkms-gpio4/status","okay\0")
    (endpoint/"wsprrypi,route").write_bytes((1).to_bytes(4,"big"))
    (endpoint/"compatible").write_bytes(b"wsprrypi,rp1-gpclk-dkms-v1\0")
    (endpoint/"clocks").write_bytes(b"\0\0\0\x01\0\0\0\x21")
    release=root/"release"; release.mkdir()
    write(root,"/release/rp1-gpclk-compatibility-manifest.json",{"manifestId":"manifest","entries":[{"id":"entry","route":"GPIO4","state":"Compatible-unqualified","operationalReady":False,"reason":"build only"}]})
    write(root,"/release/release-metadata.json",{"release":module.VERSION})
    write(root,"/release/SHA256SUMS","0"*64+"  fixture\n")
    report=module.Collector(root,runner,kernel,"aarch64").collect(release)
    assert report["readOnly"] is True
    assert report["summary"]["category"]=="build-compatible-but-live-disabled"
    assert report["compatibility"]["selectedEntry"]=="entry"
    assert report["module"]["file"]["sha256"]
    assert report["module"]["signatureStatus"]["status"]=="signed"
    assert report["module"]["outputInhibit"]["value"]=="0"
    assert report["kernels"]["headers"][kernel]["present"] is True
    assert report["endpoint"]["present"] is False
    assert report["endpoint"]["bound"] is False
    assert report["passiveSnapshot"]==snapshot
    assert report["routeOverlay"]["topology"]=="exactly-one"
    assert report["routeOverlay"]["moduleRouteMatchesActiveEndpoint"] is True
    properties=report["routeOverlay"]["activeEndpointNodes"][0]["propertyIdentities"]
    assert properties["compatible"]["status"]=="ok" and properties["compatible"]["sha256"]
    assert properties["clocks"]["sizeBytes"]==8 and properties["dmas"]["status"]=="absent"
    assert module.QUERY_SIZE==296 and module.SNAPSHOT_SIZE==384
    assert module.CAPS[0]=="submit-events" and module.CAPS[8]=="bounded-dma-chunks"
    assert set(report) >= set(contract["requiredSections"])

    development=root/"development.json"
    write(root,"/development.json",{"schema":"rp1-gpclk-source-development-manifest","classification":"source-development","qualification":False,"moduleName":module.MODULE,"sourceCommit":"a"*40,"renderedVersion":VERSION,"targetKernel":kernel,"route":"gpio4"})
    development_report=module.Collector(root,runner,kernel,"aarch64").collect(None,development)
    assert development_report["development"]["status"]=="ok"
    assert development_report["summary"]["compatibilityState"]=="Experimental"
    assert development_report["development"]["releaseQualified"] is False

    gpio20=root/"sys/firmware/devicetree/base/axi/rp1/rp1-gpclk-dkms-gpio20"; gpio20.mkdir(parents=True)
    write(root,"/sys/firmware/devicetree/base/axi/rp1/rp1-gpclk-dkms-gpio20/status","okay\0")
    (gpio20/"wsprrypi,route").write_bytes((2).to_bytes(4,"big"))
    ambiguous=module.Collector(root,runner,kernel,"aarch64").collect(release)
    assert ambiguous["routeOverlay"]["topology"]=="ambiguous"
    assert ambiguous["routeOverlay"]["moduleRouteMatchesActiveEndpoint"] is False

    for state,category in (("Qualified","healthy-and-qualified"),("Experimental","healthy-but-experimental"),
                           ("Compatible-unqualified","build-compatible-but-live-disabled"),("Unavailable","unavailable"),("Rejected","rejected")):
        q={**query,"compatibilityState":state}
        selected={"status":state,"reason":"fixture","selectedEntry":"entry"}
        assert module.classify(q,selected,{"status":"absent"})["category"]==category
    denied={"status":"indeterminate","reason":"permission-denied"}
    assert module.classify(denied,{"status":"indeterminate"},{"status":"absent"})["category"].startswith("indeterminate")
    interrupted={"status":"ok","value":{"status":"inactive-recovery-required"}}
    assert module.classify(query,{"status":"Compatible-unqualified"},interrupted)["category"]=="rejected"
    assert module.select_manifest_entry({"entries":[]},query)["status"]=="Unavailable"
    duplicate={"entries":[{"id":"entry","route":"GPIO4"},{"id":"entry","route":"GPIO4"}]}
    assert module.select_manifest_entry(duplicate,query)["status"]=="Unavailable"
    exact_missing={"status":"Unavailable","reason":"no-unique-exact-manifest-entry"}
    assert module.classify({**query,"compatibilityState":"Qualified"},exact_missing,{"status":"absent"})["category"]=="unavailable"
    mismatch={"status":"Experimental","reason":"manifest experimental"}
    assert module.classify({**query,"compatibilityState":"Qualified"},mismatch,{"status":"absent"})["category"]=="rejected"

    residue=root/"owned"; residue.mkdir()
    journal={"status":"ok","value":{"status":"inactive-recovery-required","ownedFiles":[{"path":"/owned/file"}],"ownedDirectories":["/owned"]}}
    write(root,"/owned/file","x")
    found=module.Collector(root,runner,kernel)._residue(journal)
    assert found["status"]=="interrupted-operation-residue" and found["paths"]==["/owned","/owned/file"]

def snapshot_payload(**changes):
    values=[384,0,0,1,3,1,3,2,3,0x7,1,1,1,1,2,2,2,2,2,0,0,
            0x1ff,9,100,200,1_000,9_000,
            b"rp1_gpclk_dkms",b"build",b"compat",0,0,0,0,0,0,0,0]
    indexes={"size":0,"header_reserved":1,"header_flags":2,"route":3,"compat_state":4,
             "operation":6,"terminal":7,"snapshot_flags":9,"cleanup":10,
             "owner":11,"lease":12,"output_inhibited":13,"operational_ready":14,
             "drain":15,"gpio":16,"clock":17,"dma":18,"stable":19,
             "reserved0":20,"capabilities":21,"generation":22,"elapsed":23,
             "remaining":24,"reserved1":30}
    for name,value in changes.items(): values[indexes[name]]=value
    return struct.pack(module.SNAPSHOT_FORMAT,*values)

decoded=module.decode_passive_snapshot(snapshot_payload())
assert decoded["status"]=="ok" and decoded["generation"]==9
assert decoded["elapsedNs"]==100 and decoded["remainingNs"]==200
assert decoded["nonOwning"] is True and decoded["leaseTokenExposed"] is False
running=module.decode_passive_snapshot(snapshot_payload(operation=1,terminal=0,drain=0,
    owner=2,lease=2,gpio=1,clock=1,dma=1,stable=1))
assert running["operationState"]=="RUNNING" and running["ownerPresent"]=="true"
assert running["leasePresent"]=="true" and "leaseId" not in running
draining=module.decode_passive_snapshot(snapshot_payload(operation=2,terminal=0,drain=1,stable=1))
assert draining["operationState"]=="DRAINING" and draining["drainState"]=="active"
complete=module.decode_passive_snapshot(snapshot_payload(operation=3,terminal=1,drain=2,owner=1,lease=1))
assert complete["operationState"]=="COMPLETE" and complete["drainState"]=="complete"
failed=module.decode_passive_snapshot(snapshot_payload(operation=4,terminal=13,cleanup=2,stable=1))
assert failed["operationState"]=="FAILED" and failed["cleanupFault"]=="true"
for field in ("gpio","clock","dma"):
    assert module.decode_passive_snapshot(snapshot_payload(**{field:1}))[{"gpio":"gpioSafe","clock":"clockQuiescent","dma":"dmaQuiescent"}[field]]=="false"
assert module.decode_passive_snapshot(snapshot_payload(snapshot_flags=0))["elapsedNs"] is None
for changes,reason in (({"size":383},"malformed-snapshot-header"),
                       ({"header_reserved":1},"malformed-snapshot-header"),
                       ({"header_flags":1},"malformed-snapshot-header"),
                       ({"snapshot_flags":8},"unknown-snapshot-flags"),
                       ({"route":99},"unknown-snapshot-enum"),
                       ({"stable":99},"unknown-snapshot-enum"),
                       ({"capabilities":0x200},"unknown-snapshot-capability"),
                       ({"reserved1":1},"nonzero-snapshot-reserved")):
    assert module.decode_passive_snapshot(snapshot_payload(**changes))["reason"]==reason
assert module.decode_passive_snapshot(snapshot_payload()[:-1])["reason"]=="malformed-snapshot-size"

# Exercise descriptor closure without accessing a real endpoint.
original_open,original_ioctl,original_close=module.os.open,module.fcntl.ioctl,module.os.close
closed=[]
try:
    module.os.open=lambda *_args,**_kwargs: 71
    module.fcntl.ioctl=lambda _fd,_request,buffer,_mutate: buffer.__setitem__(slice(None),snapshot_payload())
    module.os.close=lambda descriptor: closed.append(descriptor)
    assert module.Collector().passive_snapshot()["status"]=="ok" and closed==[71]
    closed.clear()
    def rejected(*_args,**_kwargs): raise OSError(5,"fixture")
    module.fcntl.ioctl=rejected
    assert module.Collector().passive_snapshot()["status"]=="rejected" and closed==[71]
    closed.clear()
    def unsupported(*_args,**_kwargs): raise OSError(module.errno.ENOTTY,"fixture")
    module.fcntl.ioctl=unsupported
    assert module.Collector().passive_snapshot()["status"]=="unsupported" and closed==[71]
    module.os.open=lambda *_args,**_kwargs: (_ for _ in ()).throw(PermissionError())
    assert module.Collector().passive_snapshot()["reason"]=="permission-denied"
    module.os.open=lambda *_args,**_kwargs: (_ for _ in ()).throw(FileNotFoundError())
    assert module.Collector().passive_snapshot()["reason"]=="endpoint-absent"
finally:
    module.os.open,module.fcntl.ioctl,module.os.close=original_open,original_ioctl,original_close

source=(ROOT/"scripts/rp1-gpclk-diagnostics.py").read_text()
for prohibited in ("modprobe","dtoverlay","dkms add","dkms build","dkms install","/dev/mem","sign-file"):
    assert prohibited not in source
for required in ("O_RDONLY","QUERY_IOCTL","SNAPSHOT_IOCTL","permission-denied","journalctl","cleanupFaultLatch"):
    assert required in source
operator=(ROOT/"engineering/operations/diagnostics.md").read_text()
assert "does not prove absence" in operator
assert commands and all(command[0] in {"dpkg-query","dkms","modinfo","journalctl"} for command in commands)
print("diagnostics contracts: PASS")
