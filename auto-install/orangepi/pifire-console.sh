#!/usr/bin/env bash
#
# HDMI screen for PiFire (Orange Pi fork).  Run as root:
#     bash pifire-console.sh
# The HDMI display module (display/hdmi_1024x600.py) draws in the framebuffer
# the Linux console also uses: the login prompt on tty1 and the blinking cursor
# would show over the PiFire screens.  This removes the login on tty1 and turns
# the console cursor off (now and at every boot).  The boot messages still
# scroll before PiFire starts; SSH and the emergency Wi-Fi stay the way in.
# Idempotent: setup.sh and the OTA updater (ota-system.sh) both run it.

set -u
TMPFILES_DIR=${TMPFILES_DIR:-/etc/tmpfiles.d}   # overridable for the tests
UNIT=getty@tty1.service
CONF="$TMPFILES_DIR/pifire-console.conf"

if systemctl is-enabled --quiet "$UNIT" || systemctl is-active --quiet "$UNIT"; then
	systemctl disable --now "$UNIT" >/dev/null 2>&1
	LOGIN="login su tty1 tolto"
else
	LOGIN="login su tty1 già tolto"
fi

mkdir -p "$TMPFILES_DIR"
echo 'w /sys/class/graphics/fbcon/cursor_blink - - - - 0' > "$CONF"
systemd-tmpfiles --create "$CONF" >/dev/null 2>&1
echo "Schermo HDMI per PiFire: $LOGIN, cursore della console spento"
exit 0
