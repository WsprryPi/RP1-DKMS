// SPDX-License-Identifier: MIT
#include <cstdio>
#include <cstdlib>
#include <fcntl.h>
#include <sys/ioctl.h>

static int forbidden_open(const char *, int, ...)
{
    std::fputs("offline sweep test attempted to open an endpoint\n", stderr);
    std::abort();
}

static int forbidden_ioctl(int, unsigned long, ...)
{
    std::fputs("offline sweep test attempted an ioctl\n", stderr);
    std::abort();
}

/* The real CLI/renderer runs with endpoint and SDR access replaced by stubs. */
#define open forbidden_open
#define ioctl forbidden_ioctl
#include "development_frequency_sweep.cpp"
