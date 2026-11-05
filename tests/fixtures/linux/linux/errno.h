/* SPDX-License-Identifier: MIT */
#ifndef RP1_GPCLK_TEST_LINUX_ERRNO_H
#define RP1_GPCLK_TEST_LINUX_ERRNO_H

/* Avoid glibc's errno.h -> linux/errno.h recursion when this fixture shadows
 * the kernel header during portable host compilation. */
#define EPERM 1
#define EIO 5
#define EBUSY 16
#define EINVAL 22
#define ERANGE 34
#define EUCLEAN 117
#define ECANCELED 125

#endif /* RP1_GPCLK_TEST_LINUX_ERRNO_H */
