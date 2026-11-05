# SPDX-License-Identifier: MIT
"""Closed snapshot field projection from one bounded native modinfo record."""
import re
import stat
from lifecycle_results import require

FIELDS = {'version': 'version', 'signer': 'signer', 'signatureKey': 'sig_key',
          'signatureAlgorithm': 'sig_id', 'signatureHash': 'sig_hashalgo',
          'controllerInterlock': 'rp1_runtime_controller', 'depends': 'depends',
          'aliases': 'alias', 'vermagic': 'vermagic'}


def module_stamp(path):
    value = path.lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1
            and value.st_size <= 64*1024*1024, 'unsafe snapshot module')
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_nlink)


def metadata(result):
    require(result.returncode == 0, 'modinfo failed')
    text = result.stdout
    require(isinstance(text, str) and 0 < len(text.encode()) <= 65536
            and text.endswith('\0'), 'modinfo output bounds/framing')
    fields = {}
    for record in text[:-1].split('\0'):
        match = re.fullmatch(r'([A-Za-z0-9_]+)[=:](.*)', record, re.S)
        require(match is not None, 'malformed modinfo field')
        key, value = match.groups()
        fields.setdefault(key, []).append(value.strip())
    for name in ('version', 'vermagic'):
        require(len(fields.get(name, [])) == 1 and fields[name][0], 'missing module identity: '+name)
    result = {}
    for output, name in FIELDS.items():
        values = fields.get(name, [])
        require(name == 'alias' or len(values) <= 1, 'duplicate modinfo field: '+name)
        require(all('\n' not in value and '\r' not in value for value in values),
                'multiline snapshot field: '+name)
        result[output] = '\n'.join(values)
    return result
