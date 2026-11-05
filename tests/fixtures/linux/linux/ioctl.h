/* SPDX-License-Identifier: MIT */
#ifndef RP1_GPCLK_TEST_LINUX_IOCTL_H
#define RP1_GPCLK_TEST_LINUX_IOCTL_H

/* Linux generic ioctl encoding used only for host-side contract tests. */
#define _IOC_NRBITS 8
#define _IOC_TYPEBITS 8
#define _IOC_SIZEBITS 14
#define _IOC_DIRBITS 2
#define _IOC_NRSHIFT 0
#define _IOC_TYPESHIFT (_IOC_NRSHIFT + _IOC_NRBITS)
#define _IOC_SIZESHIFT (_IOC_TYPESHIFT + _IOC_TYPEBITS)
#define _IOC_DIRSHIFT (_IOC_SIZESHIFT + _IOC_SIZEBITS)
#define _IOC_NONE 0U
#define _IOC_WRITE 1U
#define _IOC_READ 2U
#define _IOC(dir, type, nr, size) \
    (((dir) << _IOC_DIRSHIFT) | ((type) << _IOC_TYPESHIFT) | \
     ((nr) << _IOC_NRSHIFT) | ((size) << _IOC_SIZESHIFT))
#define _IOC_TYPE(nr) (((nr) >> _IOC_TYPESHIFT) & 0xffU)
#define _IOC_NR(nr) (((nr) >> _IOC_NRSHIFT) & 0xffU)
#define _IOC_SIZE(nr) (((nr) >> _IOC_SIZESHIFT) & 0x3fffU)
#define _IOC_DIR(nr) (((nr) >> _IOC_DIRSHIFT) & 0x3U)
#define _IOW(type, nr, data_type) _IOC(_IOC_WRITE, (type), (nr), sizeof(data_type))
#define _IOWR(type, nr, data_type) \
    _IOC(_IOC_READ | _IOC_WRITE, (type), (nr), sizeof(data_type))

#endif /* RP1_GPCLK_TEST_LINUX_IOCTL_H */
