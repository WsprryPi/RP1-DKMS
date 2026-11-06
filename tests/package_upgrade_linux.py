#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real passive package upgrade/retry/absence tests in a restricted container.

Run only in the lifecycle image with a read-only /source and a new /results.
No host device/system mounts, networking, module or service capabilities.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, '/source/scripts')
from version_identity import VERSION, DEBIAN, PACKAGE, parse, debian_version
from release_contract import inventory, package_members, sha


def main():
    assert Path('/.dockerenv').is_file() and os.geteuid() == 0, 'disposable container required'
    status = Path('/proc/self/status').read_text()
    caps = int(next(line.split()[1] for line in status.splitlines() if line.startswith('CapEff:')),16)
    assert caps & ~0xc9 == 0, 'only package filesystem/user-switch capabilities permitted'
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    for path in ('/boot','/lib/modules','/usr','/etc','/var/lib/dkms'):
        assert not any(line.split()[4] == path for line in mounts), 'system bind mount refused'
    assert not any(line.split()[1] == '00000000' for line in Path('/proc/net/route').read_text().splitlines()[1:])
    output = Path('/results')
    assert output.is_dir() and not any(output.iterdir()), 'new external results directory required'
    core, _, _ = parse(VERSION)
    successor = f'{core[0]}.{core[1]}.{core[2]+1}'
    revision = DEBIAN.rsplit('-',1)[1]
    versions = (VERSION,successor)
    with tempfile.TemporaryDirectory(prefix='rp1-real-upgrade-') as temporary:
        base=Path(temporary)
        packages={}; sources={}
        for number,version in enumerate((*versions, VERSION, successor)):
            source=base/str(number)/'source';source.parent.mkdir()
            shutil.copytree('/source',source,ignore=shutil.ignore_patterns('.git','__pycache__','build'))
            header=source/'include/rp1_gpclk/version.h'
            selected_revision = str(int(revision)+1) if number == 3 else revision
            header.write_text(header.read_text().replace('"'+VERSION+'"','"'+version+'"').replace(
                '#define RP1_GPCLK_DEBIAN_REVISION "'+revision+'"',
                '#define RP1_GPCLK_DEBIAN_REVISION "'+selected_revision+'"'))
            if number == 2:
                member=source/'src/rp1_gpclk_compatibility.c'
                member.write_text(member.read_text()+'\n#include <linux/module.h>\nMODULE_INFO(developer_replacement, "fixture");\n')
            with (output/('build-'+str(number)+'.log')).open('wb') as log:
                subprocess.run(['python3',str(source/'scripts/version_identity.py'),'prepare-debian','--root',str(source)],check=True,stdout=log,stderr=log)
                subprocess.run(['dpkg-buildpackage','--no-sign','-b'],cwd=source,stdout=log,stderr=log,check=True,timeout=600,
                    env={**os.environ,'SOURCE_DATE_EPOCH':'1700000000','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'})
            package=source.parent/(PACKAGE+'_'+debian_version(version,selected_revision)+'_all.deb')
            assert package.is_file()
            if number == 2:
                conflict=package
            elif number == 3:
                revision_package=package; revision_source=source
            else:
                packages[version]=package;sources[version]=source
        candidate=output/'candidate';candidate.mkdir()
        package=candidate/packages[successor].name
        shutil.copyfile(packages[successor],package);packages[successor]=package
        members,_=package_members(package)
        (candidate/'rp1-gpclk-dkms-installation-manifest-v1.json').write_text(json.dumps({
            'sourceCommit':subprocess.check_output(['git','-c','safe.directory=/source','-C','/source','rev-parse','HEAD'],text=True).strip(),
            'package':{'sha256':sha(package.read_bytes())},'packageInventory':inventory(members)}))
        spec=importlib.util.spec_from_file_location('lifecycle_fixture','/source/tests/package_lifecycle_linux.py')
        lifecycle=importlib.util.module_from_spec(spec);spec.loader.exec_module(lifecycle)
        lifecycle.VERSION=successor;lifecycle.DEBIAN=debian_version(successor,revision)
        lifecycle.DEB=package;lifecycle.OLD=packages[VERSION]
        Path('/candidate').symlink_to(candidate)
        lifecycle.setup()
        def run(stage,*command,expected=0):
            return lifecycle.run(stage,list(command),expected)
        spec=importlib.util.spec_from_file_location('provider_preflight', '/source/scripts/provider_lifecycle.py')
        provider=importlib.util.module_from_spec(spec);sys.modules[spec.name]=provider;spec.loader.exec_module(provider)
        def preflight(version):
            # Synthetic version trees have no Git checkout identity. Only that
            # authentication seam is replaced: the production caller, subprocess,
            # package reader, CLI parser, and host-state guard all execute.
            resolved={'checkout':{},'packagePath':str(packages[version])}
            with mock.patch.object(provider, 'revalidate_checkout', return_value=sources[version]):
                provider.package_preflight(resolved, 'unpack', provider.Runner())
        preflight(VERSION)
        run('install-A','dpkg','-i',str(packages[VERSION]))
        original=lifecycle.snapshot()
        stamps={m['path']:Path(m['path']).stat().st_mtime_ns for m in original['modules']}
        preflight(VERSION)
        run('repeat-A','dpkg','-i',str(packages[VERSION]))
        assert stamps == {p:Path(p).stat().st_mtime_ns for p in stamps}, 'repeat rebuilt installed modules'
        run('preflight-same-version-replacement','python3','-I',str(sources[VERSION]/'scripts/package_preflight.py'),
            'unpack','--package',str(conflict))
        run('replace-same-version-build','dpkg','-i',str(conflict))
        replacement=lifecycle.snapshot()
        assert all(m['version'] == VERSION for m in replacement['modules'])
        assert any(m['installedFileSha256'] != n['installedFileSha256']
                   for m,n in zip(replacement['modules'],original['modules'])), 'changed source was not rebuilt'
        packages[VERSION]=conflict
        stamps={m['path']:Path(m['path']).stat().st_mtime_ns for m in replacement['modules']}
        Path('/usr/libexec/rp1-gpclk-dkms/version_identity.py').unlink()
        preflight(VERSION)
        run('repair-missing-identity-helper','dpkg','-i',str(packages[VERSION]))
        assert stamps == {p:Path(p).stat().st_mtime_ns for p in stamps}, 'helper repair rebuilt modules'
        assert not Path('/usr/libexec/rp1-gpclk-dkms/__pycache__').exists(), 'unowned helper bytecode'
        preflight(successor)
        lifecycle.installed(run('upgrade-A-to-B','dpkg','-i',str(package)))
        assert not Path('/usr/src',PACKAGE+'-'+VERSION).exists(), 'old source retained'
        assert not Path('/var/lib/dkms',PACKAGE,VERSION).exists(), 'old DKMS retained'
        assert not Path('/usr/share',PACKAGE,VERSION).exists(), 'old versioned schema retained'
        run('preflight-packaging-revision','python3','-I',str(revision_source/'scripts/package_preflight.py'),
            'unpack','--package',str(revision_package))
        lifecycle.DEBIAN=debian_version(successor,str(int(revision)+1))
        lifecycle.installed(run('upgrade-packaging-revision','dpkg','-i',str(revision_package)))
        run('refuse-downgrade','python3','-I',str(sources[VERSION]/'scripts/package_preflight.py'),
            'unpack','--package',str(packages[VERSION]),expected=1)
        lifecycle.installed(lifecycle.snapshot())
        run('remove-B','dpkg','--remove',PACKAGE)
        lifecycle.absent(lifecycle.snapshot())
        run('purge-B','dpkg','--purge',PACKAGE)
        lifecycle.absent(lifecycle.snapshot())
        lifecycle.DEBIAN=debian_version(successor,revision)
        preflight(VERSION)
        run('reinstall-A','dpkg','-i',str(packages[VERSION]))
        preflight(successor)
        Path('/tmp/lifecycle-fault').write_text('build')
        run('interrupted-upgrade','dpkg','-i',str(package),expected=1)
        Path('/tmp/lifecycle-fault').unlink(missing_ok=True)
        lifecycle.installed(run('retry-upgrade-configure','dpkg','--configure',PACKAGE))
        run('final-remove','dpkg','--remove',PACKAGE)
        lifecycle.absent(lifecycle.snapshot())
        run('final-purge','dpkg','--purge',PACKAGE)
        lifecycle.absent(lifecycle.snapshot())
        result={'status':'PASS','versions':list(versions),'steps':lifecycle.STEPS,
                'hardwareQualification':False,'rfQualification':False}
        (output/'upgrade-result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'status':'PASS','versions':list(versions),'completedSteps':len(lifecycle.STEPS)}))


if __name__ == '__main__':
    main()
