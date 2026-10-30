#!/usr/bin/env bash
#
# Device access for the user PiFire runs as (Orange Pi fork).  Run as root:
#     bash pifire-devices.sh <user>
# Installs 60-pifire-devices.rules (gpiochip -> group gpio, spidev -> group spi),
# puts the user in the gpio, spi and i2c groups and applies the rule now.
# Idempotent: setup.sh and the OTA updater (ota-system.sh) both run it.
# A process started before the change keeps its old groups: restart PiFire
# (sudo supervisorctl restart all) or reboot.

set -u
RUN_USER="${1:?usage: pifire-devices.sh <user>}"
UDEV_DIR=${UDEV_DIR:-/etc/udev/rules.d}	# overridable for the tests
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$UDEV_DIR"
cp "$HERE/60-pifire-devices.rules" "$UDEV_DIR/60-pifire-devices.rules"
for group in gpio spi i2c; do
	getent group "$group" >/dev/null || groupadd --system "$group"
	if [[ "$RUN_USER" != "root" ]] && id "$RUN_USER" >/dev/null 2>&1; then
		usermod -a -G "$group" "$RUN_USER"
	fi
done
if command -v udevadm >/dev/null; then
	udevadm control --reload-rules
	udevadm trigger --subsystem-match=gpio --subsystem-match=spidev --action=change
	udevadm settle --timeout=5 2>/dev/null
fi
echo "Accesso a GPIO, SPI e I2C per l'utente $RUN_USER: $(ls -l /dev/gpiochip* 2>/dev/null | awk '{print $1, $3":"$4, $NF}' | tr '\n' ' ')"
exit 0
