#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

package=rp1-gpclk-dkms
module=rp1_gpclk_dkms

usage()
{
	cat >&2 <<EOF
usage: $0 preflight SOURCE_DIR
       $0 add|build|install|uninstall|remove SOURCE_DIR
       $0 load-disabled|unload|status SOURCE_DIR
       $0 sign SOURCE_DIR PRIVATE_KEY X509_CERTIFICATE
       $0 overlay-build SOURCE_DIR OUTPUT_DIR
       $0 overlay-install SOURCE_DIR gpio4|gpio20 [OVERLAY_DIRECTORY]
EOF
	exit 2
}

run()
{
	printf 'COMMAND'
	printf ' %s' "$@"
	printf '\n'
	"$@"
}

action=${1:-}
source_dir=${2:-}
if [ -z "$action" ] || [ -z "$source_dir" ]; then
	usage
fi
source_dir=$(realpath "$source_dir")
if [ ! -d "$source_dir" ] || [ -L "$source_dir" ]; then
	echo "source must be a real directory" >&2
	exit 2
fi
version=$(sed -n 's/^PACKAGE_VERSION="\([0-9A-Za-z][0-9A-Za-z._+-]*\)"$/\1/p' "$source_dir/dkms.conf")
[ -n "$version" ] || { echo "invalid DKMS version" >&2; exit 2; }
kernel_release=$(uname -r)
kernel_build="/lib/modules/$kernel_release/build"

preflight()
{
	[ "$(uname -m)" = aarch64 ] || { echo "unsupported architecture" >&2; exit 1; }
	grep -aRq 'raspberrypi,rp1' /proc/device-tree || { echo "RP1 device-tree identity unavailable" >&2; exit 1; }
	[ -d "$kernel_build" ] || { echo "missing running-kernel headers" >&2; exit 1; }
	command -v dkms >/dev/null || { echo "DKMS unavailable" >&2; exit 1; }
	grep -q '^AUTOINSTALL="yes"$' "$source_dir/dkms.conf"
	grep -q "RP1_GPCLK_MODULE_VERSION \"$version\"" "$source_dir/include/rp1_gpclk/version.h"
	printf 'package=%s version=%s kernel=%s architecture=%s output_inhibit=enabled\n' \
		"$package" "$version" "$kernel_release" "$(uname -m)"
}

case "$action" in
preflight)
	preflight
	;;
add)
	preflight
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	destination="/usr/src/$package-$version"
	[ ! -e "$destination" ] || { echo "source destination already exists" >&2; exit 1; }
	run install -d -m 0755 "$destination"
	run cp -a "$source_dir/." "$destination/"
	run dkms add -m "$package" -v "$version"
	;;
build|install|uninstall|remove)
	preflight
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	case "$action" in
	build) run dkms build -m "$package" -v "$version" -k "$kernel_release" ;;
	install) run dkms install -m "$package" -v "$version" -k "$kernel_release" ;;
	uninstall) run dkms uninstall -m "$package" -v "$version" -k "$kernel_release" ;;
	remove) run dkms remove -m "$package" -v "$version" --all ;;
	esac
	;;
load-disabled)
	preflight
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	run modprobe "$module" output_inhibit=1
	[ "$(cat "/sys/module/$module/parameters/output_inhibit")" = Y ] || { echo "output inhibit is not enabled" >&2; exit 1; }
	;;
unload)
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	run modprobe -r "$module"
	;;
status)
	preflight
	dkms status -m "$package" -v "$version" || true
	if [ -e "/sys/module/$module/parameters/output_inhibit" ]; then
		printf 'loaded output_inhibit=%s\n' "$(cat "/sys/module/$module/parameters/output_inhibit")"
	else
		echo 'not loaded'
	fi
	;;
sign)
	preflight
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	key=${3:-}; certificate=${4:-}
	if [ ! -f "$key" ] || [ -L "$key" ] || [ ! -f "$certificate" ] || [ -L "$certificate" ]; then
		usage
	fi
	module_path=$(modinfo -n "$module")
	if [ ! -f "$module_path" ] || [ -L "$module_path" ]; then
		echo "installed module unavailable" >&2
		exit 1
	fi
	run "$kernel_build/scripts/sign-file" sha256 "$key" "$certificate" "$module_path"
	modinfo "$module_path" | grep -E '^(signer|sig_key|sig_hashalgo):'
	;;
overlay-build)
	output=${3:-}; [ -n "$output" ] || usage
	output=$(realpath -m "$output")
	[ ! -e "$output" ] || { echo "overlay output already exists" >&2; exit 1; }
	command -v dtc >/dev/null || { echo "dtc unavailable" >&2; exit 1; }
	common_headers="/usr/src/linux-headers-${kernel_release%+rpt-rpi-2712}+rpt-common-rpi/include"
	[ -d "$common_headers" ] || { echo "DT headers unavailable" >&2; exit 1; }
	run install -d -m 0755 "$output"
	for route in gpio4 gpio20; do
		cpp -nostdinc -I "$common_headers" -undef -x assembler-with-cpp \
			"$source_dir/overlays/rp1-gpclk-$route.dts" >"$output/rp1-gpclk-$route.pp.dts"
		run dtc -@ -I dts -O dtb -o "$output/rp1-gpclk-$route.dtbo" \
			"$output/rp1-gpclk-$route.pp.dts"
	done
	;;
overlay-install)
	[ "$(id -u)" -eq 0 ] || { echo "root required" >&2; exit 1; }
	route=${3:-}; overlay_dir=${4:-/boot/firmware/overlays}
	case "$route" in gpio4|gpio20) ;; *) echo "route must be gpio4 or gpio20" >&2; exit 2 ;; esac
	if [ ! -d "$overlay_dir" ] || [ -L "$overlay_dir" ]; then
		echo "unsafe overlay directory" >&2
		exit 1
	fi
	artifact="$source_dir/rp1-gpclk-$route.dtbo"
	if [ ! -f "$artifact" ] || [ -L "$artifact" ]; then
		echo "built overlay unavailable" >&2
		exit 1
	fi
	destination="$overlay_dir/rp1-gpclk-$route.dtbo"
	[ ! -e "$destination" ] || cmp -s "$artifact" "$destination" || { echo "refusing to replace nonidentical overlay" >&2; exit 1; }
	[ -e "$destination" ] || run install -m 0644 "$artifact" "$destination"
	run cmp "$artifact" "$destination"
	;;
*) usage ;;
esac
