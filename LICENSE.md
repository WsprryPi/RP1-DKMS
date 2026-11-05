<!-- SPDX-License-Identifier: MIT -->

# Licensing policy

Copyright (c) 2026 Lee Bussy

The project uses per-file SPDX identifiers. The identifier in each file is the
authoritative license for that file.

## Original project work

| Material | SPDX expression | Reason |
| --- | --- | --- |
| Loadable kernel-module source and kernel-facing shared implementation | `GPL-2.0-only OR MIT` | Preserves MIT availability while providing an explicit GPLv2 choice appropriate for Linux module integration |
| Userspace-visible UAPI headers | `(GPL-2.0-only WITH Linux-syscall-note) OR MIT` | Preserves a clear userspace boundary and MIT reuse |
| Independent build tools, packaging scripts, tests, documentation, schemas, and metadata | `MIT` | Uses the project owner's preferred permissive license where practical |
| Device-tree sources authored here | `GPL-2.0-only OR MIT` | Keeps kernel/firmware-facing material compatible and reusable |

The loadable module must declare:

```c
MODULE_LICENSE("Dual MIT/GPL");
```

`MODULE_LICENSE()` is kernel-loader metadata and does not replace the SPDX
identifier or license notice in each source file.

## License texts

- [MIT License](LICENSES/MIT.txt)
- [GNU General Public License version 2 only](LICENSES/GPL-2.0-only.txt)
- [Linux syscall exception](LICENSES/Linux-syscall-note.txt)

## Contributions and imported material

By contributing original work, a contributor agrees to license it under the
SPDX expression already assigned to the destination file. A contribution that
requires another license must be identified and accepted before it is merged.

Third-party and adapted material retains its applicable license, copyright,
attribution, and provenance. Do not copy code merely because it is publicly
visible. Material derived from the Linux kernel or another GPL-only source may
need to remain GPL-only and must not be relabeled MIT.

This policy expresses the project's intended licensing structure; it is not
legal advice and does not decide whether a particular adaptation is a
derivative work.
