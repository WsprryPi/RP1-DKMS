<!-- SPDX-License-Identifier: MIT -->

# RP1 GPCLK DKMS

RP1-GPCLK-DKMS lets WsprryPi control the RP1 clock output on Raspberry Pi 5
and Compute Module 5 systems. It provides the kernel modules and managed route
service used to send a signal through **GPIO4** or **GPIO20**. DKMS builds the
modules for the installed stock Raspberry Pi kernel.

**Install and manage RP1 support through WsprryPi.** Most operators only need
to choose a route in WsprryPi and check its status. This handbook explains
those steps and the occasional maintenance tasks that need an administrator.

## Start with your task

If WsprryPi is already installed, start with
[use an installed system](getting-started.md). You do not need to install RP1
again or switch an already correct route merely to check it.

| Task | Where to go |
| --- | --- |
| Open WsprryPi and check an existing installation | [Use an installed system](getting-started.md) |
| Stop output before a change | [Make the transmitter idle](getting-started.md#make-the-transmitter-idle) |
| Set up a new Raspberry Pi | [Install with WsprryPi](installation.md) |
| Choose GPIO4 or GPIO20 | [Select or remove a route](routes.md) |
| Understand a status message | [Read provider status](status.md) |
| Update the system or recover an interrupted change | [Maintenance and recovery](maintenance.md) |
| Collect information about a failure | [Troubleshooting](troubleshooting.md) and [support](support.md) |
| Inspect the provider from a terminal | [Command-line reference](command-line.md) |

Installing software or choosing a route does not start a transmission. Before
operating, follow the [RF and electrical precautions](safety.md) and WsprryPi's
band and mode guidance for your installed version.

## Choose the right documentation version

Use the Read the Docs version selector to choose **main** for maintained
operator documentation or **devel** for development-branch documentation.
The `latest` alias follows `main`. These names identify documentation branches;
they do not select or update software on your Pi. Match WsprryPi's own manual
to the application version you have installed.

```{toctree}
:maxdepth: 2
:caption: Start here

about
getting-started
installation
safety
```

```{toctree}
:maxdepth: 2
:caption: Operate and maintain

routes
status
maintenance
troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Reference and help

command-line
faq
support
```
