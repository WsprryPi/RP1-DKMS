#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify installed PKCS#7 signatures against the selected public certificate.

Independent parser for the on-disk format in Linux include/linux/module_signature.h.
Certificate matching/validity here does not establish running-kernel trust.
"""
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

MAGIC = b'~Module signature appended~\n'


class SignatureFailure(Exception):
    def __init__(self, result):
        self.result = result


def split_signature(data):
    if not data.endswith(MAGIC) or len(data) < len(MAGIC)+12:
        raise ValueError('required module signature is absent')
    end = len(data)-len(MAGIC)-12
    header = data[end:end+12]
    if header[:8] != b'\0\0\x02\0\0\0\0\0':
        raise ValueError('unsupported module signature trailer')
    length = struct.unpack('>I', header[8:])[0]
    if not 0 < length <= 1024*1024 or end-length < 6:
        raise ValueError('module signature length is invalid')
    unsigned = data[:end-length]
    if not unsigned.startswith(b'\x7fELF\x02\x01'):
        raise ValueError('signed module is not ELF64 little endian')
    return unsigned, data[end-length:end]


def verify(data, certificate, module_path):
    try:
        unsigned, signature = split_signature(data)
    except ValueError as error:
        raise SignatureFailure({'stage': 'signature', 'command': ['signature-trailer', str(module_path)],
                                'exitStatus': 1, 'diagnostic': str(error)}) from error

    def command(args):
        argv = ['/usr/bin/openssl', *map(str, args)]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=15,
                                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'OPENSSL_CONF': '/dev/null'})
        except subprocess.TimeoutExpired as error:
            raise SignatureFailure({'stage': 'signature', 'command': argv, 'exitStatus': 124,
                                    'diagnostic': str(error)[:4096]}) from error
        except OSError as error:
            raise SignatureFailure({'stage': 'signature', 'command': argv, 'exitStatus': 127,
                                    'diagnostic': str(error)[:4096]}) from error
        if result.returncode:
            raise SignatureFailure({'stage': 'signature', 'command': argv,
                'exitStatus': result.returncode, 'diagnostic': (result.stdout+result.stderr)[-8192:]})

    with tempfile.TemporaryDirectory(prefix='rp1-package-signature-', dir='/tmp') as temporary:
        root = Path(temporary)
        cert, der = root/'signer.pem', root/'signer.der'
        content, cms = root/'module.elf', root/'signature.der'
        content.write_bytes(unsigned)
        cms.write_bytes(signature)
        encoding = 'PEM' if certificate.read_bytes().startswith(b'-----BEGIN CERTIFICATE-----') else 'DER'
        command(['x509', '-inform', encoding, '-in', certificate, '-out', cert])
        command(['x509', '-in', cert, '-outform', 'DER', '-out', der])
        command(['verify', '-purpose', 'any', '-partial_chain', '-CAfile', cert, cert])
        command(['cms', '-verify', '-binary', '-inform', 'DER', '-in', cms, '-content', content,
                 '-certfile', cert, '-nointern', '-noverify', '-out', '/dev/null'])
        return {'module': str(module_path), 'certificateSha256': hashlib.sha256(der.read_bytes()).hexdigest(),
                'signatureVerified': True, 'certificateValidityVerified': True, 'kernelTrustVerified': False}
