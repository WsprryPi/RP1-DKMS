#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded, read-only RP1-GPCLK-DKMS diagnostics."""

from __future__ import annotations
import argparse, errno, fcntl, grp, hashlib, json, os, pathlib, platform, pwd, stat, struct, subprocess
from typing import Callable

PACKAGE, MODULE, VERSION = "rp1-gpclk-dkms", "rp1_gpclk_dkms", "0.99.0"
DEVICE = "/dev/rp1-gpclk"
FILE_LIMIT, LOG_LIMIT, COMMAND_LIMIT, TIMEOUT = 4096, 16384, 8192, 5
# The UAPI uses __aligned_u64, so native C alignment is part of the ioctl size.
QUERY_FORMAT = "@HHI" + "I"*4 + "Q" + "I"*4 + "Q"*3 + "64s"*3 + "Q"*4
SNAPSHOT_FORMAT = "@HHI" + "I"*18 + "Q"*6 + "64s"*3 + "Q"*8
QUERY_SIZE, SNAPSHOT_SIZE = struct.calcsize(QUERY_FORMAT), struct.calcsize(SNAPSHOT_FORMAT)
QUERY_IOCTL = 0xC0000000 | (QUERY_SIZE << 16) | (0xB8 << 8) | 0x20
SNAPSHOT_IOCTL = 0xC0000000 | (SNAPSHOT_SIZE << 16) | (0xB8 << 8) | 0x28
STATES = {1:"Qualified",2:"Experimental",3:"Compatible-unqualified",4:"Unavailable",5:"Rejected"}
REASONS = {0:"none",1:"manifest-missing",2:"identity-unknown",3:"identity-mismatch",4:"build-unsupported",5:"signature-rejected",6:"resource-unavailable",7:"resource-conflict",8:"self-test-failed",9:"cleanup-latched"}
ROUTES = {1:"GPIO4",2:"GPIO20"}
CAPS = {0:"submit-events",1:"stop-drain",2:"stable-state",3:"route-identity",
        4:"compat-identity",5:"cleanup-fault-latch",6:"output-inhibit",
        7:"passive-snapshot",8:"bounded-dma-chunks"}
OPERATION_STATES = {0:"IDLE",1:"RUNNING",2:"DRAINING",3:"COMPLETE",4:"FAILED",5:"DEAD"}
TERMINAL_REASONS = {0:"none",1:"complete",2:"stopped",3:"owner-closed",4:"provider-removed",5:"deadline-missed",6:"invalid-request",7:"resource-unavailable",8:"startup-conflict",9:"dma-failed",10:"clock-failed",11:"pinctrl-failed",12:"readback-failed",13:"cleanup-failed",14:"compatibility-rejected",15:"internal-error"}
OBSERVATIONS = {0:"unknown",1:"false",2:"true"}
DRAIN_STATES = {0:"none",1:"active",2:"complete"}
SNAPSHOT_FLAGS = {0:"current-event-valid",1:"elapsed-valid",2:"remaining-valid"}

def decode_passive_snapshot(payload: bytes) -> dict:
    if len(payload)!=SNAPSHOT_SIZE: return {"status":"rejected","reason":"malformed-snapshot-size"}
    values=struct.unpack(SNAPSHOT_FORMAT,payload)
    if values[0]!=SNAPSHOT_SIZE or values[1]!=0 or values[2]!=0:
        return {"status":"rejected","reason":"malformed-snapshot-header"}
    route,compat_state,compat_reason,operation,terminal,current_event,flags,cleanup,owner,lease,output_inhibited,operational_ready,drain,gpio_safe,clock_quiescent,dma_quiescent,stable,reserved0=values[3:21]
    if reserved0 or flags & ~0x7: return {"status":"rejected","reason":"unknown-snapshot-flags"}
    observations=(cleanup,owner,lease,output_inhibited,operational_ready,gpio_safe,clock_quiescent,dma_quiescent,stable)
    if route not in ROUTES or compat_state not in STATES or compat_reason not in REASONS or operation not in OPERATION_STATES or terminal not in TERMINAL_REASONS or drain not in DRAIN_STATES or any(item not in OBSERVATIONS for item in observations):
        return {"status":"rejected","reason":"unknown-snapshot-enum"}
    capabilities,generation,elapsed,remaining,min_tone,max_tone=values[21:27]
    if capabilities & ~0x1ff: return {"status":"rejected","reason":"unknown-snapshot-capability"}
    if any(values[index] != 0 for index in range(30,38)): return {"status":"rejected","reason":"nonzero-snapshot-reserved"}
    valid={name:bool(flags&(1<<bit)) for bit,name in SNAPSHOT_FLAGS.items()}
    return {"status":"ok","route":ROUTES[route],"compatibilityState":STATES[compat_state],"compatibilityReason":REASONS[compat_reason],
        "operationState":OPERATION_STATES[operation],"terminalReason":TERMINAL_REASONS[terminal],
        "currentEvent":current_event if valid["current-event-valid"] else None,"generation":generation,
        "elapsedNs":elapsed if valid["elapsed-valid"] else None,"remainingNs":remaining if valid["remaining-valid"] else None,
        "cleanupFault":OBSERVATIONS[cleanup],"ownerPresent":OBSERVATIONS[owner],"leasePresent":OBSERVATIONS[lease],
        "outputInhibited":OBSERVATIONS[output_inhibited],"operationalReady":OBSERVATIONS[operational_ready],"drainState":DRAIN_STATES[drain],
        "gpioSafe":OBSERVATIONS[gpio_safe],"clockQuiescent":OBSERVATIONS[clock_quiescent],"dmaQuiescent":OBSERVATIONS[dma_quiescent],"stable":OBSERVATIONS[stable],
        "capabilityMask":f"0x{capabilities:016x}","capabilities":[name for bit,name in CAPS.items() if capabilities&(1<<bit)],
        "dmaChunkDurationNs":min_tone,"maxRequestDurationNs":max_tone,
        "moduleId":values[27].split(b"\0",1)[0].decode(errors="replace"),"buildId":values[28].split(b"\0",1)[0].decode(errors="replace"),"compatibilityId":values[29].split(b"\0",1)[0].decode(errors="replace"),
        "nonOwning":True,"leaseTokenExposed":False,"descriptorClosed":True}

def sha256(path: pathlib.Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file(): return None
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(65536): digest.update(chunk)
        return digest.hexdigest()
    except OSError: return None

class Collector:
    """Collector supports a synthetic root/runner solely for hardware-free tests."""
    def __init__(self, root=pathlib.Path("/"), runner: Callable[[list[str]],dict]|None=None,
                 kernel: str|None=None, architecture: str|None=None):
        self.root, self.runner = pathlib.Path(root), runner or self._run
        self.kernel, self.architecture = kernel or platform.release(), architecture or platform.machine()
    def path(self, absolute: str) -> pathlib.Path: return self.root / absolute.lstrip("/")
    @staticmethod
    def _run(args: list[str]) -> dict:
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=TIMEOUT, check=False,
                env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"})
            return {"status":"ok" if result.returncode == 0 else "error", "exitStatus":result.returncode,
                    "stdout":result.stdout[:COMMAND_LIMIT], "stderr":result.stderr[:COMMAND_LIMIT],
                    "truncated":len(result.stdout)>COMMAND_LIMIT or len(result.stderr)>COMMAND_LIMIT}
        except FileNotFoundError: return {"status":"unavailable","reason":"command-not-found"}
        except subprocess.TimeoutExpired: return {"status":"indeterminate","reason":"command-timeout"}
    def read(self, absolute: str, limit=FILE_LIMIT) -> dict:
        try:
            path=self.path(absolute)
            if path.is_symlink() or not path.is_file(): return {"status":"absent"}
            data=path.read_bytes()
            return {"status":"ok","value":data[:limit].decode(errors="replace").rstrip("\0\n"),"truncated":len(data)>limit}
        except PermissionError: return {"status":"indeterminate","reason":"permission-denied"}
        except OSError as error: return {"status":"indeterminate","reason":type(error).__name__}
    def metadata(self, absolute: str) -> dict:
        try:
            value=self.path(absolute).lstat()
            kind="symlink" if stat.S_ISLNK(value.st_mode) else "character" if stat.S_ISCHR(value.st_mode) else "file" if stat.S_ISREG(value.st_mode) else "other"
            return {"status":"ok","present":True,"type":kind,"uid":value.st_uid,"gid":value.st_gid,
                    "owner":pwd.getpwuid(value.st_uid).pw_name,"group":grp.getgrgid(value.st_gid).gr_name,
                    "mode":f"{stat.S_IMODE(value.st_mode):04o}"}
        except FileNotFoundError: return {"status":"ok","present":False}
        except PermissionError: return {"status":"indeterminate","reason":"permission-denied"}
        except (OSError,KeyError) as error: return {"status":"indeterminate","reason":type(error).__name__}
    def json_file(self, absolute: str) -> dict:
        item=self.read(absolute)
        if item["status"]!="ok": return item
        try: return {"status":"ok","value":json.loads(item["value"]),"sha256":sha256(self.path(absolute))}
        except json.JSONDecodeError: return {"status":"rejected","reason":"malformed-json"}
    def query(self) -> dict:
        if self.root != pathlib.Path("/"):
            fixture=self.json_file("/run/rp1-gpclk-dkms/query-fixture.json")
            return fixture.get("value",fixture) if fixture.get("status")=="ok" else fixture
        try:
            descriptor=os.open(self.path(DEVICE),os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK)
            try:
                payload=bytearray(QUERY_SIZE); struct.pack_into("<HHI",payload,0,QUERY_SIZE,0,0)
                fcntl.ioctl(descriptor,QUERY_IOCTL,payload,True)
                values=struct.unpack(QUERY_FORMAT,payload)
            finally: os.close(descriptor)
            bits=values[7]
            reason=REASONS.get(values[5],f"unknown-{values[5]}")
            result={"status":"ok","route":ROUTES.get(values[3],f"unknown-{values[3]}"),
                "compatibilityState":STATES.get(values[4],f"unknown-{values[4]}"),"compatibilityReason":REASONS.get(values[5],f"unknown-{values[5]}"),
                "cleanupFault":reason=="cleanup-latched",
                "capabilityMask":f"0x{bits:016x}","capabilities":[name for bit,name in CAPS.items() if bits&(1<<bit)],
                "unknownCapabilityMask":f"0x{bits&~0x1ff:016x}","moduleId":values[15].split(b"\0",1)[0].decode(errors="replace"),
                "buildId":values[16].split(b"\0",1)[0].decode(errors="replace"),"compatibilityId":values[17].split(b"\0",1)[0].decode(errors="replace"),
                "maxTones":values[8],"maxEvents":values[9],"maxDitherPeriod":values[10],
                "supportedDriveMaMask":f"0x{values[11]:08x}","maxEventDurationNs":values[12],
                "maxRequestDurationNs":values[13],"dmaChunkDurationNs":values[14]}
            return result
        except PermissionError: return {"status":"indeterminate","reason":"permission-denied"}
        except FileNotFoundError: return {"status":"unavailable","reason":"endpoint-absent"}
        except OSError as error: return {"status":"rejected","reason":f"query-failed-{error.errno}"}
    def passive_snapshot(self) -> dict:
        if self.root != pathlib.Path("/"):
            fixture=self.json_file("/run/rp1-gpclk-dkms/passive-snapshot-fixture.json")
            return fixture.get("value",fixture) if fixture.get("status")=="ok" else fixture
        descriptor=None
        try:
            descriptor=os.open(self.path(DEVICE),os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK)
            payload=bytearray(SNAPSHOT_SIZE)
            struct.pack_into("<HHI",payload,0,SNAPSHOT_SIZE,0,0)
            fcntl.ioctl(descriptor,SNAPSHOT_IOCTL,payload,True)
            return decode_passive_snapshot(payload)
        except PermissionError: return {"status":"indeterminate","reason":"permission-denied"}
        except FileNotFoundError: return {"status":"unavailable","reason":"endpoint-absent"}
        except OSError as error:
            return {"status":"unsupported","reason":"passive-snapshot-unsupported"} if error.errno in {errno.EOPNOTSUPP,errno.ENOTTY} else {"status":"rejected","reason":f"snapshot-failed-{error.errno}"}
        finally:
            if descriptor is not None: os.close(descriptor)
    def collect(self, release_directory: pathlib.Path|None=None, development_manifest: pathlib.Path|None=None) -> dict:
        module_candidates=[]
        module_directory=self.path(f"/lib/modules/{self.kernel}/updates/dkms")
        if module_directory.is_dir():
            module_candidates=sorted(path for path in module_directory.glob(f"{MODULE}.ko*") if path.is_file() and not path.is_symlink())
        module_local=module_candidates[0] if len(module_candidates)==1 else self.path(f"/lib/modules/{self.kernel}/updates/dkms/{MODULE}.ko")
        module_path="/"+str(module_local.relative_to(self.root)) if self.root!=pathlib.Path("/") else str(module_local)
        kernels=sorted(p.name for p in self.path("/lib/modules").glob("*") if p.is_dir())
        module_file=self.metadata(module_path); module_file["sha256"]=sha256(self.path(module_path)); module_file["compression"]="none" if module_local.name.endswith(".ko") else module_local.suffix.lstrip(".")
        modinfo={name:self.runner(["modinfo","-F",field,module_path]) for name,field in
            (("version","version"),("vermagic","vermagic"),("signer","signer"),("signatureKeyId","sig_key"),("signatureAlgorithm","sig_id"),("signatureHashAlgorithm","sig_hashalgo"))}
        transaction=self.json_file(f"/var/lib/{PACKAGE}/transaction.json")
        query=self.query(); snapshot=self.passive_snapshot(); release=self._release(release_directory)
        selected=select_manifest_entry(release.get("manifest"),query)
        endpoint=self.metadata(DEVICE); driver=self.path("/sys/bus/platform/drivers/rp1-gpclk-dkms")
        endpoint["boundDevices"]=sorted(p.name for p in driver.glob("*") if p.name not in {"bind","unbind","module","uevent"})[:8]
        endpoint["bound"]=bool(endpoint["boundDevices"])
        development=self._development(development_manifest)
        result={"SPDX-License-Identifier":"MIT","schemaVersion":1,"readOnly":True,
            "collectionLimits":{"commandSeconds":TIMEOUT,"commandStreamBytes":COMMAND_LIMIT,"fileBytes":FILE_LIMIT,"kernelLogBytes":LOG_LIMIT,"kernelLogScope":"current boot, matching rp1_gpclk or rp1-gpclk only"},
            "summary":classify(query,selected,transaction),
            "package":{"version":VERSION,"manager":self.runner(["dpkg-query","-W","-f=${Status} ${Version}",PACKAGE]),"dkms":self.runner(["dkms","status","-m",PACKAGE])},
            "kernels":{"running":self.kernel,"installed":kernels,"headers":{k:self.metadata(f"/lib/modules/{k}/build") for k in kernels}},
            "build":{"transaction":transaction,"logs":self._build_logs()},
            "module":{"installedPath":module_path,"file":module_file,"metadata":modinfo,
                      "signatureStatus":self._signature_status(modinfo),"loaded":self.path(f"/sys/module/{MODULE}").is_dir(),"outputInhibit":self.read(f"/sys/module/{MODULE}/parameters/output_inhibit"),"taint":self.read("/proc/sys/kernel/tainted")},
            "endpoint":endpoint,"uapi":query,"passiveSnapshot":snapshot,"release":release,"compatibility":selected,
            "authority":{"model":"root-owned-endpoint","requiredUid":0,"requiredGid":0,"requiredMode":"0600"},
            "cleanupFaultLatch":query.get("cleanupFault","not-exposed-by-QUERY-v1") if query.get("status")=="ok" else query,
            "routeOverlay":self._route_overlay(query),"hardwareIdentity":self._hardware(),
            "kernelDiagnostics":self.runner(["journalctl","-k","-b","--no-pager","-g","rp1[_-]gpclk","--output=short-monotonic"]),
            "residue":self._residue(transaction),"assurance":"A clean report does not prove absence of competing or direct-MMIO software."}
        result["development"]=development
        if development.get("status")=="ok":
            result["summary"]={"category":"healthy-but-experimental" if query.get("status")=="ok" else "source-development",
                               "compatibilityState":"Experimental","reason":"exact-source-development-manifest; not release-qualified"}
        return result
    @staticmethod
    def _development(supplied):
        if supplied is None: return {"status":"not-supplied"}
        try:
            path=pathlib.Path(supplied); value=json.loads(path.read_text())
            if (value.get("schema")!="rp1-gpclk-source-development-manifest" or
                    value.get("classification")!="source-development" or value.get("qualification") is not False or
                    value.get("moduleName")!=MODULE): return {"status":"rejected","reason":"invalid-development-manifest","path":str(path)}
            return {"status":"ok","path":str(path),"sha256":sha256(path),"classification":"Experimental",
                    "releaseQualified":False,"sourceCommit":value.get("sourceCommit"),"renderedVersion":value.get("renderedVersion"),
                    "targetKernel":value.get("targetKernel"),"route":value.get("route")}
        except (OSError,json.JSONDecodeError): return {"status":"rejected","reason":"unreadable-development-manifest","path":str(supplied)}
    def _release(self,supplied):
        base=pathlib.Path(supplied) if supplied else self.path(f"/usr/share/{PACKAGE}/{VERSION}")
        result={"path":str(base),"status":"ok" if base.is_dir() and not base.is_symlink() else "absent"}
        for name in ("release-metadata.json","rp1-gpclk-compatibility-manifest.json","SHA256SUMS"):
            digest=sha256(base/name); result[name]={"status":"ok","sha256":digest} if digest else {"status":"absent"}
        try:
            path=base/"rp1-gpclk-compatibility-manifest.json"
            if path.is_file() and not path.is_symlink(): result["manifest"]=json.loads(path.read_text())
        except (OSError,json.JSONDecodeError): result["manifest"]={"status":"rejected","reason":"malformed-or-unreadable"}
        return result
    def _build_logs(self):
        logs=[]
        for path in sorted(self.path(f"/var/lib/dkms/{PACKAGE}").glob("*/*/*/log/make.log"))[:8]:
            try:
                data=path.read_bytes(); logs.append({"path":str(path.relative_to(self.root)),"tail":data[-LOG_LIMIT:].decode(errors="replace"),"truncated":len(data)>LOG_LIMIT})
            except OSError: logs.append({"path":str(path),"status":"indeterminate","reason":"permission-denied-or-read-error"})
        return logs
    def _route_overlay(self,query):
        route=query.get("route") if query.get("status")=="ok" else None
        name={"GPIO4":"rp1-gpclk-gpio4.dtbo","GPIO20":"rp1-gpclk-gpio20.dtbo"}.get(route)
        nodes=[]; of_root=self.path("/sys/firmware/devicetree/base")
        if of_root.is_dir():
            for endpoint_name, expected_route in (("rp1-gpclk-dkms-gpio4","GPIO4"),("rp1-gpclk-dkms-gpio20","GPIO20")):
                for node in sorted(of_root.rglob(endpoint_name))[:2]:
                    status=self._dt_property(node/"status") or "okay"
                    raw_route=self._dt_bytes(node/"wsprrypi,route")
                    route_number=int.from_bytes(raw_route,"big") if raw_route and len(raw_route)==4 else None
                    nodes.append({"name":endpoint_name,"path":str(node.relative_to(of_root)),"status":status,
                                  "declaredRoute":ROUTES.get(route_number,f"unknown-{route_number}"),"expectedRoute":expected_route,
                                  "propertyIdentities":{property_name:self._dt_identity(node/property_name) for property_name in
                                      ("compatible","reg","clocks","clock-names","dmas","dma-names","pinctrl-names")}})
        active=[item for item in nodes if item["status"]=="okay"]
        return {"selectedRoute":route or "indeterminate","selectedArtifact":name,"artifactSha256":sha256(self.path(f"/boot/firmware/overlays/{name}")) if name else None,
                "persistentConfiguration":self.read("/boot/firmware/config.txt",LOG_LIMIT),"activeEndpointNodes":active,
                "topology":"exactly-one" if len(active)==1 else "none" if not active else "ambiguous",
                "moduleRouteMatchesActiveEndpoint":len(active)==1 and active[0]["declaredRoute"]==route and active[0]["expectedRoute"]==route}
    def _hardware(self):
        result={name:self.read(path) for name,path in {"model":"/proc/device-tree/model","revision":"/proc/device-tree/system/linux,revision","firmwareVersion":"/sys/firmware/devicetree/base/chosen/bootloader/version"}.items()}
        result["baseDeviceTreeSha256"]=sha256(self.path("/sys/firmware/fdt"))
        return result
    @staticmethod
    def _dt_bytes(path:pathlib.Path)->bytes|None:
        try: return path.read_bytes() if path.is_file() and not path.is_symlink() else None
        except OSError: return None
    @classmethod
    def _dt_property(cls,path:pathlib.Path)->str|None:
        value=cls._dt_bytes(path)
        return value.rstrip(b"\0").decode(errors="replace") if value is not None else None
    @classmethod
    def _dt_identity(cls,path:pathlib.Path)->dict:
        value=cls._dt_bytes(path)
        return {"status":"absent"} if value is None else {
            "status":"ok","sizeBytes":len(value),"sha256":hashlib.sha256(value).hexdigest()}
    @staticmethod
    def _signature_status(modinfo):
        signer=modinfo["signer"]
        if signer.get("status")!="ok": return {"status":"indeterminate","reason":"modinfo-signer-unavailable"}
        return {"status":"signed" if signer.get("stdout","").strip() else "unsigned",
                "reason":"metadata-present" if signer.get("stdout","").strip() else "no-signer-metadata"}
    def _residue(self,transaction):
        if transaction.get("status")!="ok" or not isinstance(transaction.get("value"),dict): return {"status":"indeterminate" if transaction.get("status")=="indeterminate" else "none-recorded","paths":[]}
        journal=transaction["value"]; paths=[]
        for item in journal.get("ownedFiles",[]):
            candidate=item.get("path") if isinstance(item,dict) else None
            if candidate and self.path(candidate).exists(): paths.append(candidate)
        for candidate in journal.get("ownedDirectories",[]):
            if isinstance(candidate,str) and self.path(candidate).exists(): paths.append(candidate)
        interrupted=journal.get("status") not in {"complete","recovered"}; unique=sorted(set(paths))
        return {"status":"interrupted-operation-residue" if interrupted and unique else "none-detected","transactionStatus":journal.get("status","unknown"),"paths":unique[:128],"truncated":len(unique)>128}

def select_manifest_entry(manifest,query):
    if not isinstance(manifest,dict) or not isinstance(manifest.get("entries"),list): return {"status":"Unavailable","reason":"manifest-missing-or-malformed","selectedEntry":None}
    if query.get("status")!="ok": return {"status":"indeterminate","reason":"UAPI-query-unavailable","selectedEntry":None,"manifestId":manifest.get("manifestId")}
    matches=[e for e in manifest["entries"] if e.get("id")==query.get("compatibilityId") and e.get("route")==query.get("route")]
    if len(matches)!=1: return {"status":"Unavailable","reason":"no-unique-exact-manifest-entry","selectedEntry":None,"manifestId":manifest.get("manifestId")}
    entry=matches[0]; return {"status":entry.get("state","Rejected"),"reason":entry.get("reason","missing-reason"),"selectedEntry":entry.get("id"),"manifestId":manifest.get("manifestId"),"operationalReady":entry.get("operationalReady",False)}

def classify(query,selected,transaction):
    if transaction.get("status")=="ok" and transaction.get("value",{}).get("status") not in {"complete","recovered"}: return {"category":"rejected","compatibilityState":"Rejected","reason":"interrupted-operation-requires-recovery"}
    if any(x.get("status")=="indeterminate" for x in (query,selected)): return {"category":"indeterminate-because-inspection-lacked-privileges","compatibilityState":"indeterminate","reason":"required-read-denied-or-query-unavailable"}
    state=query.get("compatibilityState") if query.get("status")=="ok" else selected.get("status","Unavailable")
    if query.get("cleanupFault") is True or state=="Rejected": return {"category":"rejected","compatibilityState":"Rejected","reason":query.get("compatibilityReason",selected.get("reason"))}
    if selected.get("status")=="Unavailable": return {"category":"unavailable","compatibilityState":"Unavailable","reason":selected.get("reason")}
    if selected.get("status") not in {state,"indeterminate"}: return {"category":"rejected","compatibilityState":"Rejected","reason":"UAPI-and-manifest-state-mismatch"}
    categories={"Qualified":"healthy-and-qualified","Experimental":"healthy-but-experimental","Compatible-unqualified":"build-compatible-but-live-disabled"}
    if state in categories: return {"category":categories[state],"compatibilityState":state,"reason":selected.get("reason")}
    return {"category":"unavailable","compatibilityState":"Unavailable","reason":selected.get("reason",query.get("reason","required-identity-unavailable"))}

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--release-directory",type=pathlib.Path)
    parser.add_argument("--development-manifest",type=pathlib.Path); args=parser.parse_args()
    if args.release_directory and args.development_manifest: parser.error("choose a release directory or a development manifest, not both")
    print(json.dumps(Collector().collect(args.release_directory,args.development_manifest),indent=2,sort_keys=True))
if __name__=="__main__": main()
