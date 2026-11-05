#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install and authenticate a passive exact-source route manager without replacing package files."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, re, shutil, socket, stat, subprocess, sys, time

SCHEMA="rp1-gpclk-route-manager-source-development-v1"
ADOPTION_SCHEMA="rp1-gpclk-route-manager-current-boot-adoption"
MANIFEST_SCHEMA="rp1-gpclk-source-development-manifest"
BASE="/opt/rp1-gpclk-dkms-development"
DROPIN="/etc/systemd/system/rp1-gpclk-route-manager@.service.d/90-source-development.conf"
UNIT="rp1-gpclk-route-manager@source-development-status.service"
RECORD="/var/lib/rp1-gpclk-dkms/development/route-manager.json"
PACKAGE_PATHS=("/usr/sbin/rp1-gpclk-route-manager","/usr/libexec/rp1-gpclk-dkms/rp1-gpclk-route-manager","/usr/lib/systemd/system/rp1-gpclk-route-manager@.service")
COMPAT={"gpio4":"v0.99.0-rp1-gpio4","gpio20":"v0.99.0-rp1-gpio20"}

class Failure(RuntimeError): pass
def root(path:str)->pathlib.Path:
    base=pathlib.Path(os.environ.get("RP1_GPCLK_DEVELOPMENT_ROOT","/")); value=pathlib.Path(path)
    return base/str(value).lstrip("/") if base!=pathlib.Path("/") else value
def digest(path:pathlib.Path)->str:
    value=hashlib.sha256();
    with path.open("rb") as stream:
        while chunk:=stream.read(1024*1024): value.update(chunk)
    return value.hexdigest()
def canonical(value:object)->bytes: return json.dumps(value,indent=2,sort_keys=True).encode()+b"\n"
def atomic(path:pathlib.Path,payload:bytes,mode:int)->None:
    path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("xb") as stream: stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(mode); os.replace(temporary,path)
def run(argv:list[str],check:bool=True)->subprocess.CompletedProcess[str]:
    result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False,env={**os.environ,"LC_ALL":"C"})
    if check and result.returncode: raise Failure(f"command failed ({result.returncode}): {' '.join(argv)}: {result.stderr.strip()}")
    return result
def systemctl(*args:str,check:bool=True)->str:
    tool=os.environ.get("RP1_GPCLK_TOOL_SYSTEMCTL","/usr/bin/systemctl"); return run([tool,*args],check=check).stdout.strip()
def load(path:pathlib.Path)->dict:
    try: value=json.loads(path.read_text())
    except (OSError,json.JSONDecodeError) as error: raise Failure(f"JSON record is unreadable: {path}") from error
    if not isinstance(value,dict): raise Failure("JSON record is not an object")
    return value
def require_root()->None:
    if not os.environ.get("RP1_GPCLK_DEVELOPMENT_TEST_ROOT") and os.geteuid()!=0: raise Failure("operation requires root")
def observations()->dict:
    inhibit=root("/sys/module/rp1_gpclk_dkms/parameters/output_inhibit")
    if not inhibit.is_file() or inhibit.read_text().strip() not in {"N","0","Y","1"}: raise Failure("output_inhibit is absent or unknown")
    module=root("/sys/module/rp1_gpclk_dkms/refcnt"); refcount=int(module.read_text().strip()) if module.is_file() else 0
    if refcount!=0: raise Failure("module reference count is not zero")
    endpoint=root("/dev/rp1-gpclk")
    if endpoint.exists():
        meta=endpoint.stat()
        for fd in root("/proc").glob("[0-9]*/fd/*"):
            try: opened=fd.stat()
            except OSError: continue
            if (opened.st_dev,opened.st_ino)==(meta.st_dev,meta.st_ino): raise Failure("RP1 GPCLK endpoint is open")
    active=systemctl("is-active","wsprrypi.service",check=False)
    if active not in {"inactive","failed"}: raise Failure("wsprrypi.service is active or unknown")
    return {"outputInhibited":inhibit.read_text().strip() in {"Y","1"},"moduleRefcount":refcount,"endpointOpen":False,"wsprrypiService":active}
def manifest(path:pathlib.Path,route:str,kernel:str)->dict:
    value=load(path)
    if (value.get("schema")!=MANIFEST_SCHEMA or value.get("classification")!="source-development" or value.get("qualification") is not False or
            value.get("sourceState")!="clean" or value.get("targetKernel")!=kernel or value.get("route")!=route or
            value.get("renderedVersion")!="0.99.0" or not re.fullmatch(r"[0-9a-f]{40}",str(value.get("sourceCommit","")))): raise Failure("development manifest identity differs")
    return value
def package_inventory()->list[dict]:
    result=[]
    for name in PACKAGE_PATHS:
        path=root(name)
        if path.is_symlink() or not path.is_file(): raise Failure(f"packaged path is absent or unsafe: {name}")
        result.append({"path":name,"sha256":digest(path),"mode":stat.S_IMODE(path.stat().st_mode)})
    return result
def paths(commit:str)->dict[str,pathlib.Path]:
    directory=root(f"{BASE}/{commit}")
    return {"directory":directory,"executable":directory/"rp1-gpclk-route-manager","manifest":directory/"DEVELOPMENT_MANIFEST.json","binding":directory/"binding.json","adoption":directory/"current-boot-ownership.json","dropin":root(DROPIN),"record":root(RECORD)}
def archive_rolled_back_record(record_path:pathlib.Path)->dict|None:
    if not record_path.exists(): return None
    if record_path.is_symlink() or not record_path.is_file(): raise Failure("existing source-development record is unsafe")
    record=load(record_path); commit=record.get("sourceCommit",""); target=paths(commit)
    allowed={str(target[key]) for key in ("executable","manifest","binding","adoption","dropin")}
    if (record.get("schema")!=SCHEMA or record.get("classification")!="Experimental/source-development" or
            record.get("qualification") is not False or record.get("status")!="rolled-back" or
            not re.fullmatch(r"[0-9a-f]{40}",commit) or set(record.get("createdFiles",[]))!=allowed):
        raise Failure("existing source-development record is not a completed rollback")
    if any(pathlib.Path(name).exists() for name in allowed) or target["directory"].exists():
        raise Failure("rolled-back source-development artifacts still exist")
    if package_inventory()!=record.get("packageFilesBefore"): raise Failure("packaged files differ from rolled-back record")
    installed=record.get("installedAtUnix")
    if not isinstance(installed,int): raise Failure("rolled-back source-development record has no installation identity")
    archive=record_path.with_name(f"route-manager.rolled-back-{commit}-{installed}.json")
    if archive.exists() or archive.is_symlink(): raise Failure("rolled-back source-development archive already exists")
    os.replace(record_path,archive)
    return {"path":str(archive),"sha256":digest(archive),"sourceCommit":commit,"installedAtUnix":installed}
def clean_source(path:pathlib.Path)->tuple[str,pathlib.Path]:
    source=path.resolve(); executable=source/"scripts/rp1-gpclk-route-manager.py"
    if executable.is_symlink() or not executable.is_file(): raise Failure("source route-manager executable is absent or unsafe")
    commit=run(["git","-C",str(source),"rev-parse","HEAD"]).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}",commit): raise Failure("source commit is invalid")
    if run(["git","-C",str(source),"status","--porcelain"]).stdout: raise Failure("source tree is dirty")
    return commit,executable
def passive_query()->dict:
    client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); client.settimeout(5)
    try:
        client.connect("/run/rp1-gpclk-dkms/route-manager.sock"); client.sendall(b'{"operation":"query"}\n'); client.shutdown(socket.SHUT_WR)
        return json.loads(client.makefile("rb").readline())
    finally: client.close()
def install(args:argparse.Namespace)->dict:
    require_root(); safety=observations(); source=manifest(args.module_manifest,args.route,args.kernel); commit,executable=clean_source(args.source); target=paths(commit)
    predecessor=archive_rolled_back_record(target["record"])
    if target["directory"].exists() or target["dropin"].exists(): raise Failure("source-development route-manager state already exists")
    package_before=package_inventory(); previous={"unit":UNIT,"fragment":systemctl("show","-p","FragmentPath","--value",UNIT),"dropins":systemctl("show","-p","DropInPaths","--value",UNIT),"execStart":systemctl("show","-p","ExecStart","--value",UNIT)}
    record={"schema":SCHEMA,"classification":"Experimental/source-development","qualification":False,"status":"prepared","sourceCommit":commit,"moduleSourceCommit":source["sourceCommit"],"moduleManifest":str(args.module_manifest),"moduleManifestSha256":digest(args.module_manifest),"kernel":args.kernel,"route":args.route,"compatibilityId":COMPAT[args.route],"packageFilesBefore":package_before,"previousUnitResolution":previous,"createdFiles":[str(target[key]) for key in ("executable","manifest","binding","adoption","dropin")],"installedAtUnix":int(time.time()),"predecessorRollbackRecord":predecessor}
    atomic(target["record"],canonical(record),0o600)
    try:
        target["directory"].mkdir(parents=True,mode=0o755)
        shutil.copyfile(executable,target["executable"]); target["executable"].chmod(0o755)
        shutil.copyfile(args.module_manifest,target["manifest"]); target["manifest"].chmod(0o644)
        binding={"schema":SCHEMA,"classification":"Experimental/source-development","qualification":False,"sourceCommit":commit,"moduleSourceCommit":source["sourceCommit"],"sourceManifest":str(target["manifest"]),"sourceManifestSha256":digest(target["manifest"]),"executable":str(target["executable"]),"executableSha256":digest(target["executable"]),"adoptionRecord":str(target["adoption"]),"module":"rp1_gpclk_dkms","moduleVersion":"0.99.0","uapiSha256":source["uapiIdentity"]["sha256"],"kernel":args.kernel,"route":args.route,"compatibilityId":COMPAT[args.route]}
        atomic(target["binding"],canonical(binding),0o644)
        dropin=("# SPDX-License-Identifier: MIT\n[Service]\nExecStart=\n"+f"ExecStart={target['executable']}\n"+f"Environment=RP1_GPCLK_SOURCE_DEVELOPMENT_BINDING={target['binding']}\n").encode()
        atomic(target["dropin"],dropin,0o644); systemctl("daemon-reload"); systemctl("restart","rp1-gpclk-route-manager.socket")
        record.update(status="installed",binding=binding,dropinSha256=digest(target["dropin"])); atomic(target["record"],canonical(record),0o600)
        return {"status":"deployed-awaiting-current-boot-adoption","record":str(target["record"]),"sourceCommit":commit,"adoptionCommand":f"sudo ./scripts/development-route-manager adopt-current-boot --record {target['record']}"}
    except BaseException:
        try: rollback(argparse.Namespace(record=target["record"]))
        except BaseException: pass
        raise
def status(args:argparse.Namespace)->dict:
    record=load(args.record); commit=record.get("sourceCommit",""); target=paths(commit)
    if record.get("schema")!=SCHEMA or record.get("classification")!="Experimental/source-development" or record.get("qualification") is not False or record.get("status")!="installed": raise Failure("source-development record is incomplete")
    safety=observations(); binding=load(target["binding"])
    if binding!=record.get("binding") or digest(target["executable"])!=binding.get("executableSha256") or digest(target["manifest"])!=binding.get("sourceManifestSha256") or digest(target["dropin"])!=record.get("dropinSha256"): raise Failure("active source-development artifact identity differs")
    package_after=package_inventory()
    if package_after!=record["packageFilesBefore"]: raise Failure("Debian-owned route-manager files changed")
    dropins=systemctl("show","-p","DropInPaths","--value",UNIT); resolved=systemctl("show","-p","ExecStart","--value",UNIT)
    if str(target["dropin"]) not in dropins or str(target["executable"]) not in resolved: raise Failure("systemd does not resolve the exact source-development executable")
    adoption=load(target["adoption"])
    boot=root("/proc/sys/kernel/random/boot_id"); config=root("/boot/firmware/config.txt")
    adoption_fields={"schema","classification","qualification","adoptedAtUnix","bootId","configSha256","route","sourceCommit","executableSha256","moduleSourceCommit","moduleManifestSha256","moduleVersion","uapiSha256","kernel","compatibilityId"}
    if (set(adoption)!=adoption_fields or adoption.get("schema")!=ADOPTION_SCHEMA or adoption.get("classification")!="Experimental/source-development" or
            adoption.get("qualification") is not False or not isinstance(adoption.get("adoptedAtUnix"),int) or
            adoption.get("bootId")!=(boot.read_text().strip() if boot.is_file() else None) or
            adoption.get("configSha256")!=(digest(config) if config.is_file() else None) or adoption.get("route")!=binding["route"] or
            adoption.get("sourceCommit")!=binding["sourceCommit"] or adoption.get("executableSha256")!=binding["executableSha256"] or
            adoption.get("moduleSourceCommit")!=binding["moduleSourceCommit"] or adoption.get("moduleManifestSha256")!=binding["sourceManifestSha256"] or
            adoption.get("moduleVersion")!=binding["moduleVersion"] or adoption.get("uapiSha256")!=binding["uapiSha256"] or
            adoption.get("kernel")!=binding["kernel"] or adoption.get("compatibilityId")!=binding["compatibilityId"]): raise Failure("current-boot adoption record is stale or mismatched")
    query=None
    if root("/")==pathlib.Path("/"):
        query=passive_query()
        state=query.get("state",{}) if isinstance(query,dict) else {}
        query_safety=state.get("safety",{}) if isinstance(state,dict) else {}
        if (query.get("status")!="ok" or state.get("configuredRoute")!=binding["route"] or state.get("activeRoute")!=binding["route"] or
                state.get("pendingTransaction") is not None or state.get("bootOwnership")!="current" or
                query_safety.get("endpointOwned") is not True or query_safety.get("endpointOpen") is not False or
                type(query_safety.get("outputInhibited")) is not bool or
                not isinstance(query_safety.get("services"),dict)):
            raise Failure("passive QUERY does not authenticate current ownership and exact idle safety of the selected route")
    return {"status":"ok","classification":record["classification"],"qualification":False,"sourceCommit":commit,"moduleSourceCommit":record["moduleSourceCommit"],"record":str(args.record),"binding":binding,"adoption":{"path":str(target["adoption"]),"sha256":digest(target["adoption"]),"record":adoption},"passiveQuery":query,"dropin":{"path":str(target["dropin"]),"sha256":record["dropinSha256"]},"systemd":{"dropInPaths":dropins,"execStart":resolved},"packageFiles":package_after,"safety":safety,"rollbackCommand":f"sudo ./scripts/development-route-manager rollback --record {args.record}"}
def adopt(args:argparse.Namespace)->dict:
    require_root(); record=load(args.record); commit=record.get("sourceCommit",""); target=paths(commit)
    if record.get("status")!="installed" or target["adoption"].exists(): raise Failure("deployment is not eligible for current-boot adoption")
    observations(); binding=load(target["binding"])
    query=passive_query()
    state=query.get("state",{}) if isinstance(query,dict) else {}
    if (query.get("status")!="ok" or state.get("bootOwnership")!="unadopted-source-development" or state.get("configuredRoute")!=binding["route"] or
            state.get("activeRoute")!=binding["route"] or state.get("pendingTransaction") is not None): raise Failure("deployment is not an exact idle source-development route eligible for adoption")
    adoption={"schema":ADOPTION_SCHEMA,"classification":"Experimental/source-development","qualification":False,"adoptedAtUnix":int(time.time()),
              "bootId":state["bootId"],"configSha256":state["configSha256"],"route":binding["route"],"sourceCommit":binding["sourceCommit"],
              "executableSha256":binding["executableSha256"],"moduleSourceCommit":binding["moduleSourceCommit"],"moduleManifestSha256":binding["sourceManifestSha256"],
              "moduleVersion":binding["moduleVersion"],"uapiSha256":binding["uapiSha256"],"kernel":binding["kernel"],"compatibilityId":binding["compatibilityId"]}
    atomic(target["adoption"],canonical(adoption),0o600)
    try: result=status(args)
    except BaseException:
        target["adoption"].unlink(missing_ok=True); raise
    result["adoption"]={"path":str(target["adoption"]),"sha256":digest(target["adoption"]),"record":adoption}; return result
def rollback_adoption(args:argparse.Namespace)->dict:
    require_root(); record=load(args.record); target=paths(record.get("sourceCommit","")); observations()
    if not target["adoption"].is_file() or target["adoption"].is_symlink(): raise Failure("current-boot adoption record is absent or unsafe")
    target["adoption"].unlink(); return {"status":"adoption-rolled-back","removed":str(target["adoption"]),"deploymentPreserved":True}
def rollback(args:argparse.Namespace)->dict:
    require_root(); record=load(args.record); commit=record.get("sourceCommit",""); target=paths(commit)
    if record.get("schema")!=SCHEMA or not re.fullmatch(r"[0-9a-f]{40}",commit): raise Failure("rollback record is invalid")
    observations()
    allowed={str(target[key]) for key in ("executable","manifest","binding","adoption","dropin")}
    if set(record.get("createdFiles",[]))!=allowed: raise Failure("rollback record created-file set is incomplete")
    for key in ("dropin","adoption","binding","manifest","executable"):
        path=target[key]
        if path.exists():
            if path.is_symlink() or not path.is_file(): raise Failure(f"rollback refuses altered path: {path}")
            path.unlink()
    try: target["directory"].rmdir()
    except FileNotFoundError: pass
    systemctl("daemon-reload"); systemctl("restart","rp1-gpclk-route-manager.socket")
    if package_inventory()!=record["packageFilesBefore"]: raise Failure("packaged files differ after rollback")
    record["status"]="rolled-back"; atomic(args.record,canonical(record),0o600)
    return {"status":"rolled-back","record":str(args.record),"scope":"recorded-files-only","packageFiles":record["packageFilesBefore"]}
def main()->int:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="operation",required=True)
    install_parser=sub.add_parser("install"); install_parser.add_argument("--source",type=pathlib.Path,required=True); install_parser.add_argument("--module-manifest",type=pathlib.Path,required=True); install_parser.add_argument("--route",choices=sorted(COMPAT),required=True); install_parser.add_argument("--kernel",required=True)
    for name in ("status","adopt-current-boot","rollback-adoption","rollback"): sub.add_parser(name).add_argument("--record",type=pathlib.Path,default=root(RECORD))
    args=parser.parse_args()
    try: result={"install":install,"status":status,"adopt-current-boot":adopt,"rollback-adoption":rollback_adoption,"rollback":rollback}[args.operation](args); print(json.dumps(result,indent=2,sort_keys=True)); return 0
    except (Failure,OSError,ValueError,KeyError,subprocess.SubprocessError) as error: print(f"error: {error}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
