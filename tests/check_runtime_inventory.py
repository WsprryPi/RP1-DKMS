#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real read-only collector tests with fake filesystem and bounded child processes."""
import json
import lzma
from pathlib import Path
import struct
import sys
import tempfile
import time
import subprocess
import os
import signal
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_inventory as inv
import runtime_route_client as client


def elf():
    names = b"\0.shstrtab\0.note.gnu.build-id\0"
    note = b"fixture-build-note"
    blob = bytearray(256)
    blob[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", blob, 40, 64)
    struct.pack_into("<HHH", blob, 58, 64, 3, 1)
    struct.pack_into("<IIQQQQIIQQ", blob, 128, 1, 3, 0, 0, 256, len(names), 0, 0, 0, 0)
    struct.pack_into("<IIQQQQIIQQ", blob, 192, 11, 7, 0, 0, 256 + len(names), len(note), 0, 0, 0, 0)
    return bytes(blob) + names + note


class FakeReader:
    def __init__(self):
        self.reads = []
        self.boots = 0
        self.reboot = False
        self.unknown_note = False
        self.config = b"[all]\ndtoverlay=rp1-gpclk-gpio20\n"
        self.packed = lzma.compress(elf())

    def read(self, name, limit=inv.LIMIT):
        self.reads.append(name)
        if name == inv.FILES["bootId"]:
            self.boots += 1
            if self.reboot and self.boots > 1:
                return b"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
            return b"11111111-2222-3333-4444-555555555555\n"
        if name == inv.FILES["bootConfig"]:
            return self.config
        if name == inv.FILES["outputInhibit"]:
            return b"N\n"
        if name.endswith(".ko.xz"):
            return self.packed
        if name == inv.FILES["loadedBuildNote"]:
            if self.unknown_note:
                raise PermissionError("unknown")
            return b"fixture-build-note"
        return b"fixture\n"

    def entries(self, name):
        return []

    def endpoints(self):
        return [{"path": "fixture/gpio20", "status": "6f6b617900",
                 "wsprrypi,route": "00000002", "wsprrypi,pin": "00000014"}]


def run(argv):
    assert argv in inv.COMMANDS.values()
    if argv == inv.COMMANDS["kernel"]:
        return {"status": "observed", "text": "fixture-kernel\n"}
    if argv == inv.COMMANDS["installedModule"]:
        return {"status": "observed", "text": "filename: /lib/modules/fixture-kernel/updates/dkms/rp1_gpclk_dkms.ko.xz\n"}
    return {"status": "observed", "text": "fixture\n"}


class Tests(unittest.TestCase):
    def test_real_collector_flow(self):
        reader = FakeReader()
        value = inv.collect(reader, run)
        self.assertTrue(value["sameBoot"])
        self.assertFalse(value["atomic"])
        self.assertFalse(value["assessment"]["mutationAvailable"])
        self.assertEqual(value["assessment"]["bootRouteCandidates"], ["gpio20"])
        self.assertEqual(value["assessment"]["runtimeOwnership"], "not-established")
        self.assertEqual(value["assessment"]["operationalReady"], "unknown")
        self.assertIn("boot-route-migration-review-required", value["assessment"]["blockers"])
        self.assertTrue(value["files"]["installedModuleBytes"]["buildNoteMatchesLoaded"])
        self.assertEqual(value["files"]["installedModuleBytes"]["decompressedSha256"], inv.sha(elf()))
        self.assertNotIn("/dev/rp1-gpclk", reader.reads)

    def test_reboot_and_unknown_observations(self):
        reader = FakeReader()
        reader.reboot = True
        reader.unknown_note = True
        value = inv.collect(reader, run)
        self.assertFalse(value["sameBoot"])
        self.assertIsNone(value["files"]["installedModuleBytes"]["buildNoteMatchesLoaded"])
        def failed(argv):
            return inv.unknown("timeout")
        value = inv.collect(reader, failed)
        self.assertEqual(value["files"]["installedModuleBytes"]["status"], "unknown")

    def test_configuration_is_not_treated_as_effective_state(self):
        reader = FakeReader()
        for config, candidates in [(b"include other.txt\n", []),
                                   (b"[none]\ndtoverlay=rp1-gpclk-gpio4\n", ["gpio4"]),
                                   (b"dtoverlay=rp1-gpclk-gpio4,param=1\n", ["gpio4"]),
                                   (b"#dtoverlay=rp1-gpclk-gpio4\n", [])]:
            reader.config = config
            value = inv.collect(reader, run)
            self.assertEqual(value["assessment"]["bootRouteCandidates"], candidates)
            self.assertEqual(value["assessment"]["bootSelectionInterpretation"], "candidates-only")
            self.assertFalse(value["assessment"]["mutationAvailable"])

    def test_modinfo_cannot_choose_an_arbitrary_path(self):
        for text in ("filename: /dev/rp1-gpclk\n", "filename: /tmp/module.ko.xz\n",
                     "filename: /lib/modules/other/updates/dkms/rp1_gpclk_dkms.ko.xz\n"):
            reader = FakeReader()
            def alternate(argv):
                return {"status": "observed", "text": text} if argv == inv.COMMANDS["installedModule"] else run(argv)
            value = inv.collect(reader, alternate)
            self.assertEqual(value["files"]["installedModuleBytes"]["status"], "unknown")
            self.assertFalse(any(p.endswith(".ko.xz") for p in reader.reads))
        reader = FakeReader()
        def traversal(argv):
            if argv == inv.COMMANDS["kernel"]:
                return {"status": "observed", "text": "../../foreign"}
            if argv == inv.COMMANDS["installedModule"]:
                return {"status": "observed", "text": "filename: /lib/modules/../../foreign/updates/dkms/rp1_gpclk_dkms.ko.xz\n"}
            return run(argv)
        inv.collect(reader, traversal)
        self.assertFalse(any("../" in p for p in reader.reads))

    def test_inventory_failures_remain_unknown(self):
        reader = FakeReader()
        reader.entries = lambda name: (_ for _ in ()).throw(PermissionError())
        reader.endpoints = lambda: (_ for _ in ()).throw(OSError())
        value = inv.collect(reader, run)
        self.assertEqual(value["endpoints"]["status"], "unknown")
        self.assertEqual(value["files"]["runtimeOverlays"]["status"], "unknown")
        self.assertIn("route-observation-incomplete", value["assessment"]["blockers"])

    def test_invalid_boot_id_never_reports_same_boot(self):
        reader = FakeReader()
        read = reader.read
        reader.read = lambda name, limit=inv.LIMIT: b"" if name == inv.FILES["bootId"] else read(name, limit)
        self.assertFalse(inv.collect(reader, run)["sameBoot"])

    def test_elf_and_compression_bounds(self):
        self.assertEqual(inv.module_note(elf()), b"fixture-build-note")
        for blob in (b"bad", elf()[:64], elf()[:-1]):
            with self.assertRaises(ValueError):
                inv.module_note(blob)
        for packed in (b"bad", lzma.compress(elf())[:-1], lzma.compress(elf()) + b"extra"):
            reader = FakeReader()
            reader.packed = packed
            self.assertEqual(inv.collect(reader, run)["files"]["installedModuleBytes"]["status"], "unknown")

    def test_regular_files_only_and_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record"
            path.write_bytes(b"12345")
            self.assertEqual(inv.Reader().read(str(path), 5), b"12345")
            with self.assertRaises(ValueError):
                inv.Reader().read(str(path), 4)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                inv.Reader().read(str(link))
            with self.assertRaises(ValueError):
                inv.Reader().read(tmp)

    def test_command_bounds_and_errors(self):
        self.assertEqual(inv.bounded_command((sys.executable, "-c", "print('ok')"))["text"], "ok\n")
        self.assertEqual(inv.bounded_command((sys.executable, "-c", "print('x'*1000)"), limit=50)["reason"], "command-output-limit")
        self.assertEqual(inv.bounded_command((sys.executable, "-c", "raise SystemExit(3)"))["exitCode"], 3)

    def test_timeout_starts_after_real_child_readiness(self):
        native = subprocess.Popen
        with tempfile.TemporaryDirectory() as name:
            ready = Path(name)/'ready'
            children = []
            def start(*args, **kwargs):
                child = native(*args, **kwargs)
                children.append(child)
                try:
                    deadline = time.monotonic()+30
                    while not ready.exists():
                        self.assertIsNone(child.poll(), 'child exited before readiness')
                        if time.monotonic() >= deadline: self.fail('child readiness guard exhausted')
                        time.sleep(0.01)
                except BaseException:
                    child.kill(); child.wait(timeout=30); child.stdout.close()
                    raise
                return child
            code = "import pathlib,signal,sys; pathlib.Path(sys.argv[1]).touch(); signal.pause()"
            with patch.object(inv.subprocess, 'Popen', side_effect=start):
                value = inv.bounded_command((sys.executable, '-c', code, str(ready)))
            self.assertTrue(ready.is_file())
            self.assertEqual(value['reason'], 'command-timeout')
            self.assertIsNotNone(children[0].poll())

    def test_partial_io_eof_and_cancellation(self):
        code = "import os; os.write(1,b'part'); os.write(1,b'ial')"
        self.assertEqual(inv.bounded_command((sys.executable, '-c', code))['text'], 'partial')
        # Closing stdout is not proof of exit. The wait still has a finite guard.
        code = "import os,signal; os.close(1); os.close(2); signal.pause()"
        self.assertEqual(inv.bounded_command((sys.executable, '-c', code))['status'], 'unknown')
        children = []
        native = subprocess.Popen
        def start(*args, **kwargs):
            child = native(*args, **kwargs); children.append(child); return child
        with patch.object(inv.subprocess, 'Popen', side_effect=start), \
                patch.object(inv.selectors, 'DefaultSelector', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                inv.bounded_command((sys.executable, '-c', 'import signal; signal.pause()'))
        self.assertIsNotNone(children[0].poll())

    def test_descendant_retaining_stdout_is_not_success(self):
        native = subprocess.Popen
        with tempfile.TemporaryDirectory() as name:
            pidfile = Path(name)/'descendant'
            code = "import os,pathlib,signal,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); signal.pause()"
            parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
            children = []
            def start(*args, **kwargs):
                child = native(*args, **kwargs); children.append(child)
                deadline = time.monotonic()+30
                while not pidfile.exists() or not pidfile.read_text():
                    if time.monotonic() >= deadline: raise RuntimeError('descendant readiness guard')
                    time.sleep(0.01)
                return child
            try:
                with patch.object(inv.subprocess, 'Popen', side_effect=start):
                    value = inv.bounded_command((sys.executable, '-c', parent, code, str(pidfile)))
                self.assertEqual(value['reason'], 'command-timeout')
                self.assertEqual(children[0].returncode, 0)
            finally:
                if pidfile.exists() and pidfile.read_text():
                    pid = int(pidfile.read_text())
                    try: os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    deadline = time.monotonic()+30
                    while True:
                        try: os.kill(pid, 0)
                        except ProcessLookupError: break
                        if time.monotonic() >= deadline: self.fail('owned descendant cleanup unresolved')
                        time.sleep(0.01)
                for child in children:
                    if child.poll() is None: child.kill()
                    child.wait(timeout=30)
                    child.stdout.close()

    def test_secondary_cleanup_failure_preserves_primary_observation(self):
        from unittest.mock import Mock
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired(['owned'], 5)
        with patch.object(inv.subprocess, 'Popen', return_value=child), \
                patch.object(inv.selectors, 'DefaultSelector', side_effect=PermissionError):
            value = inv.bounded_command(('owned',))
        self.assertEqual(value['reason'], 'PermissionError')
        self.assertEqual(value['cleanup']['status'], 'unresolved')
        child.kill.assert_called_once()
        child.stdout.close.assert_called_once()

    def test_socket_partial_progress_cannot_renew_transaction_budget(self):
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, value): self.timeouts.append(value)
            def connect(self, path): pass
            def sendall(self, value): pass
            def shutdown(self, how): pass
            def recv(self, length): return b'x'
            timeouts = []
        stream = Stream()
        with patch.object(client.socket, 'socket', return_value=stream), \
                patch.object(client.time, 'monotonic', side_effect=[0, 1, 2, 3, 31]):
            with self.assertRaisesRegex(TimeoutError, 'transaction timeout'):
                client.exchange({'operation': 'query'})
        self.assertEqual(stream.timeouts, [29, 28, 27])

    def test_effect_commands_are_not_available(self):
        self.assertEqual(set(inv.COMMANDS), {"kernel", "architecture", "packages", "services", "managerUnit", "installedModule"})
        for argv in inv.COMMANDS.values():
            self.assertNotIn("/usr/bin/dtoverlay", argv)
            self.assertNotIn("/usr/sbin/modprobe", argv)
            self.assertFalse(set(argv) & {"start", "stop", "restart", "reboot", "mask", "unmask"})
        self.assertFalse(any(path.startswith("/dev/") for path in inv.FILES.values()))


if __name__ == "__main__":
    __import__("nonempty_unittest").main()
