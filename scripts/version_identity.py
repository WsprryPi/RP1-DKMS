# SPDX-License-Identifier: MIT
"""Product identity and strict SemVer; independent of interface format versions.

The source header is authoritative. Packages and runtime bundles carry an exact
copy next to this helper, so retained tools never consult a newer checkout.
"""
from pathlib import Path
import json
import re
import subprocess

REPOSITORY = 'WsprryPi/RP1-DKMS'
LIFECYCLE = 'passive-dkms-v1'
PACKAGE = 'rp1-gpclk-dkms'
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def parse(value):
    if not isinstance(value, str) or len(value) > 63:
        raise ValueError('invalid or oversized semantic version')
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError('invalid semantic version: '+value)
    major, minor, patch, pre, build = match.groups()
    identifiers = pre.split('.') if pre else []
    if any(v.isdigit() and len(v) > 1 and v.startswith('0') for v in identifiers):
        raise ValueError('numeric prerelease identifier has a leading zero')
    return (int(major), int(minor), int(patch)), identifiers, build


def compare(left, right):
    """SemVer precedence; build metadata deliberately does not affect order."""
    a, ap, _ = parse(left)
    b, bp, _ = parse(right)
    if a != b:
        return (a > b) - (a < b)
    if not ap or not bp:
        return (not ap) - (not bp)
    for a, b in zip(ap, bp):
        if a == b:
            continue
        if a.isdigit() and b.isdigit():
            return (int(a) > int(b)) - (int(a) < int(b))
        if a.isdigit() != b.isdigit():
            return -1 if a.isdigit() else 1
        return (a > b) - (a < b)
    return (len(ap) > len(bp)) - (len(ap) < len(bp))


def debian_version(version, revision):
    core, pre, build = parse(version)
    if not re.fullmatch(r'[1-9][0-9]{0,8}', revision):
        raise ValueError('invalid Debian packaging revision')
    # Arbitrary SemVer prerelease identifiers are retained. dpkg, not SemVer,
    # owns their native ordering; transition() requires agreement of both orders.
    upstream = '.'.join(map(str, core)) + ('~'+'.'.join(pre) if pre else '')
    return upstream + ('+'+build if build else '') + '-'+revision


def from_header(text):
    values = []
    for field in ('MODULE_VERSION', 'DEBIAN_REVISION'):
        hits = re.findall(r'^#define RP1_GPCLK_'+field+r' "([^"\r\n]+)"$', text, re.M)
        if len(hits) != 1:
            raise ValueError('missing or ambiguous canonical '+field)
        values.append(hits[0])
    version, revision = values
    if len(version) > 48:
        raise ValueError("product version exceeds fixed UAPI identity capacity")
    return version, debian_version(version, revision)


def header_path():
    here = Path(__file__).resolve().parent
    installed = here/'version.h'
    return installed if installed.exists() else here.parent/'include/rp1_gpclk/version.h'


def identity():
    path = header_path()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('canonical version header is missing or unsafe')
    return from_header(path.read_text())


def package_filename(debian):
    """Public asset name; GitHub replaces Debian's prerelease tilde with a dot."""
    return f'{PACKAGE}_{debian.replace("~", ".")}_all.deb'


VERSION, DEBIAN = identity()
COMPATIBILITY = {route: f'v{VERSION}-rp1-{route}' for route in ('gpio4', 'gpio20')}
DEB = package_filename(DEBIAN)


def debian_compare(left, right):
    for value in (left, right):
        if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r'[0-9][0-9A-Za-z.+:~\-]*', value):
            raise ValueError('invalid Debian version')
    result = subprocess.run(['dpkg', '--compare-versions', left, 'lt', right],
                            capture_output=True, timeout=5)
    if result.returncode not in (0, 1):
        raise ValueError('Debian version comparison failed')
    if result.returncode == 0:
        return -1
    result = subprocess.run(['dpkg', '--compare-versions', left, 'gt', right],
                            capture_output=True, timeout=5)
    if result.returncode not in (0, 1):
        raise ValueError('Debian version comparison failed')
    return 1 if result.returncode == 0 else 0


def transition(old_version, old_debian, new_version=VERSION, new_debian=DEBIAN):
    semantic = compare(new_version, old_version)
    native = debian_compare(new_debian, old_debian)
    if semantic < 0 or native < 0:
        raise ValueError('downgrade requires explicit owning removal and reinstall')
    if semantic == 0 and old_version != new_version:
        return 'replace'
    if semantic > 0 and native <= 0:
        raise ValueError('SemVer and Debian ordering disagree')
    return 'upgrade' if native > 0 else 'same'


def expand(value):
    """Resolve identity placeholders in maintained machine-readable templates."""
    if isinstance(value, str):
        return value.replace('@PRODUCT_VERSION@', VERSION).replace('@DEBIAN_VERSION@', DEBIAN).replace('@PACKAGE_FILENAME@', DEB)
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    return value


def prepare_debian(root):
    path = Path(root)/'debian/changelog'
    text = path.read_text()
    if text.count('@DEBIAN_VERSION@') != 1:
        raise ValueError('Debian changelog template identity differs')
    path.write_text(text.replace('@DEBIAN_VERSION@', DEBIAN))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('field', choices=('version', 'debian', 'package', 'prepare-debian', 'json'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.field == 'prepare-debian':
        prepare_debian(args.root)
    else:
        print({'version': VERSION, 'debian': DEBIAN, 'package': DEB,
               'json': json.dumps({'productVersion': VERSION, 'debianVersion': DEBIAN, 'filename': DEB})}[args.field])
