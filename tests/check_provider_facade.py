#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Public lifecycle admission and transition failures have no native effects."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import provider_lifecycle as api
import provider_identity as identity


class Tests(unittest.TestCase):
    def candidate(self,version='12.34.56',commit='a'*40):
        return {'channel':'development','version':version,'commit':commit,
                'sourceTree':'b'*40,'versionSourceSha256':'c'*64}
    def previous(self,version='12.34.56'):
        return {'channel':'development','productVersion':version,'sourceCommit':'a'*40,
                'sourceTree':'b'*40,'versionSourceSha256':'c'*64}
    def test_generic_semver_repeat_replace_upgrade_and_downgrade(self):
        old=self.previous()
        self.assertEqual(api.classify_transition(None,self.candidate()),'install')
        self.assertEqual(api.classify_transition(old,self.candidate()),'repeat')
        self.assertEqual(api.classify_transition(old,self.candidate(commit='d'*40)),'replace')
        self.assertEqual(api.classify_transition(old,self.candidate('12.34.56+developer.2')),'replace')
        self.assertEqual(api.classify_transition(old,self.candidate('12.34.57')),'upgrade')
        with self.assertRaisesRegex(api.ContractError,'downgrade'):
            api.classify_transition(old,self.candidate('12.34.55'))
    def test_release_payload_change_is_replacement(self):
        old={'channel':'release','sourceCommit':'a'*40,'releaseTag':'v12.34.56',
             'manifest':{'productVersion':'12.34.56','debianVersion':'12.34.56-1','payload':'old'}}
        new={'channel':'release','commit':'a'*40,'releaseTag':'v12.34.56',
             'manifest':{**old['manifest'],'payload':'new'}}
        with mock.patch('version_identity.debian_compare',return_value=0):
            self.assertEqual(api.classify_transition(old,new),'replace')
    def test_duplicate_and_oversized_json_are_refused(self):
        for raw in [b'{"a":1,"a":2}',b' '* (api.MAX_API_BYTES+1)]:
            with self.assertRaises(api.ContractError):api.strict_json(raw)
    def test_identity_generic_version_and_contradictory_route(self):
        value=identity.describe();value['productVersion']='12.34.56-rc.1+test.2'
        value['debianVersion']='12.34.56~rc.1+test.2-1'
        value['compatibilityIdentities']={r:'v'+value['productVersion']+'-rp1-'+r for r in ('gpio4','gpio20')}
        identity.validate(value)
        value['compatibilityIdentities']['gpio4']='v0.0.1-rp1-gpio4'
        with self.assertRaisesRegex(ValueError,'route identities'):identity.validate(value)
    def test_missing_or_malformed_identity_fields_are_refused(self):
        for field in identity.describe():
            value=identity.describe();del value[field]
            with self.assertRaises(ValueError):identity.validate(value)
        for field,value in [('schemaVersion',True),('capabilities',[]),('uapiSha256',{}),('debianVersion','99.0.0-1'),('productVersion','9'*49+'.0.0')]:
            data=identity.describe();data[field]=value
            with self.assertRaises(ValueError):identity.validate(data)
    def test_stale_plan_refused_before_any_native_effect(self):
        from argparse import Namespace
        from contextlib import nullcontext
        args=Namespace(command='apply',debug=False,record=Path('/fixture/record'),state_dir=None,plan_sha256='stale')
        with mock.patch.object(api.os,'geteuid',return_value=0), \
             mock.patch.object(api,'lifecycle_lock',return_value=nullcontext()), \
             mock.patch.object(api,'public_plan',return_value={'planSha256':'fresh'}), \
             mock.patch.object(api,'apply') as apply:
            with self.assertRaisesRegex(api.ContractError,'plan digest changed'):api.dispatch(args)
            apply.assert_not_called()

    def test_only_created_empty_provider_directories_are_retired(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve()
            names=sorted(api.DIRECTORY_SCOPE)
            paths=[root/name.lstrip('/') for name in names]
            for path in paths:path.mkdir(parents=True)
            api.retire_created_directories({'createdDirectories':[names[0]]},root)
            self.assertFalse(paths[0].exists());self.assertTrue(paths[1].exists())
            (paths[1]/'operator').write_text('preserve')
            api.retire_created_directories({'createdDirectories':[names[1]]},root)
            self.assertEqual((paths[1]/'operator').read_text(),'preserve')
            with self.assertRaises(api.ContractError):api.retire_created_directories({'createdDirectories':['/etc/foreign']},root)

    def test_legacy_adoption_refuses_nonobject_before_receipt_creation(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve();root.chmod(0o700)
            receipt=root/'old.json';receipt.write_text('[]');receipt.chmod(0o600)
            output=root/'new.json'
            with self.assertRaisesRegex(api.ContractError,'must be an object'):
                api.adopt_receipt(Namespace(receipt=receipt,record=output),mock.Mock())
            self.assertFalse(output.exists())

    def test_legacy_adoption_checks_both_native_modules_before_new_receipt(self):
        import development_workflow as native
        from argparse import Namespace
        from contextlib import ExitStack
        for changed in [False,True]:
            with self.subTest(controllerChanged=changed),tempfile.TemporaryDirectory() as raw,ExitStack() as stack:
                root=Path(raw).resolve();root.chmod(0o700)
                source=root/'source';source.mkdir()
                manifest=source/'DEVELOPMENT_MANIFEST.json';manifest.write_text('{}')
                rollback=root/'rollback.json';rollback.write_text(json.dumps({'sourceManifestSha256':api.sha256_file(manifest)}))
                module=root/'consumer.ko';module.write_bytes(b'consumer')
                old={'schema':'wsprrypi-rp1-gpclk-dkms-ownership-v1','owner':'WsprryPi',
                     'repository':api.REPOSITORY,'channel':'development','productVersion':'12.34.56',
                     'targetKernel':'fixture','rollbackRecord':str(rollback),
                     'installedModulePath':str(module),'installedModuleSha256':api.sha256_file(module)}
                receipt=root/'old.json';receipt.write_text(json.dumps(old));receipt.chmod(0o600)
                output=root/'new.json'
                modules={name:{'installedPath':'/'+name,'installedFileSha256':'a'*64,'decompressedElfSha256':'b'*64}
                         for name in [api.MODULE_NAME,api.CONTROLLER_MODULE_NAME]}
                def resolved(kernel,version,name):
                    item=dict(modules[name])
                    if changed and name==api.CONTROLLER_MODULE_NAME:item['installedFileSha256']='c'*64
                    return item
                for name,value in [('load_ownership_record',({},None,None)),('existing_inventory',{}),
                                   ('validate_development_rollback_authority',None),('validate_runtime_development_provider',None),
                                   ('root_path',source)]:
                    stack.enter_context(mock.patch.object(api,name,return_value=value))
                stack.enter_context(mock.patch.object(native,'owned_source',return_value={'installedModules':modules}))
                stack.enter_context(mock.patch.object(native,'resolve_module',side_effect=resolved))
                args=Namespace(receipt=receipt,record=output)
                if changed:
                    with self.assertRaisesRegex(api.ContractError,'native module bytes changed'):api.adopt_receipt(args,mock.Mock())
                    self.assertFalse(output.exists())
                else:
                    api.adopt_receipt(args,mock.Mock())
                    value=json.loads(output.read_text());self.assertEqual(value['owner'],'RP1-DKMS')
                self.assertTrue(receipt.exists());self.assertFalse((root/'provider-adoption.json').exists())


if __name__=='__main__':__import__("nonempty_unittest").main()
