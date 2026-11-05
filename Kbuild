# SPDX-License-Identifier: MIT

obj-m += rp1_gpclk_dkms.o
rp1_gpclk_dkms-y := src/rp1_gpclk_main.o \
	src/rp1_gpclk_bootstrap_policy.o \
	src/rp1_gpclk_compatibility.o \
	src/rp1_gpclk_core.o \
	src/rp1_gpclk_clock_setup.o \
	src/rp1_gpclk_execution.o \
	src/rp1_gpclk_execution_machine.o \
	src/rp1_gpclk_execution_policy.o \
	src/rp1_gpclk_kernel_api.o \
	src/rp1_gpclk_lifetime.o \
	src/rp1_gpclk_resource_policy.o \
	src/rp1_gpclk_uapi_dispatch.o

ccflags-y += -I$(src)/include -I$(src)/include/uapi

# Separately identified target-test artifacts only. Production and DKMS builds
# leave this unset and contain no active fault path.
ifneq ($(strip $(RP1_TARGET_FAULT_STAGE)),)
ccflags-y += -DRP1_GPCLK_TARGET_FAULT_STAGE=$(RP1_TARGET_FAULT_STAGE)
endif

# Deliberate development-only opt-in; the default package remains unchanged.
ifeq ($(RP1_RUNTIME_CONTROLLER),1)
obj-m += rp1_route_controller.o
rp1_route_controller-y := controller/main.o
ccflags-y += -DRP1_RUNTIME_CONTROLLER -I$(src)/build/runtime-controller
endif
