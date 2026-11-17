#!/usr/bin/env bash
#
# Serial console off on pins 8 and 10 (Orange Pi fork).  Run as root:
#     bash pifire-serial-console.sh /boot/armbianEnv.txt
# The PCB v4 wires the encoder/buttons to pins 8 and 10, the debug UART (ttyS0).
# Armbian's boot.cmd adds "console=ttyS0,115200" for console=display as well as
# for console=both, so console=display left the serial console on (board,
# 2026-11-17) and systemd started a serial login on it again.  A console value
# boot.cmd does not know adds no console at all; extraargs puts the kernel
# console on the HDMI screen only.  U-Boot still uses pin 8 while booting.
# A backup of the file is left next to it (.pifire.bak).  Needs a reboot.

set -u
ENV_FILE="${1:?usage: pifire-serial-console.sh <armbianEnv.txt>}"
TMPFILES_DIR=${TMPFILES_DIR:-/etc/tmpfiles.d}                     # overridable for the tests
UART_DRIVER=${UART_DRIVER:-/sys/bus/platform/drivers/dw-apb-uart}
UART_DEVICE=5000000.serial                                       # UART0 of the H618 (pins 8 and 10)

[[ -f "$ENV_FILE.pifire.bak" ]] || cp "$ENV_FILE" "$ENV_FILE.pifire.bak"   # keep the original on a second run
if grep -q '^console=' "$ENV_FILE"; then
	sed -i -E 's/^console=.*/console=none/' "$ENV_FILE"
else
	echo 'console=none' >> "$ENV_FILE"
fi
if grep -q '^extraargs=' "$ENV_FILE"; then
	grep -qE '^extraargs=.*console=tty1' "$ENV_FILE" || sed -i -E 's/^extraargs=(.*)$/extraargs=\1 console=tty1/' "$ENV_FILE"
	sed -i -E 's/^extraargs= +/extraargs=/' "$ENV_FILE"
else
	echo 'extraargs=console=tty1' >> "$ENV_FILE"
fi
systemctl disable --now serial-getty@ttyS0.service >/dev/null 2>&1

# Without a console the UART0 driver still holds PH0/PH1 (gpioinfo: consumer=kernel)
# and the encoder cannot use them: unbind it now and at every boot.
mkdir -p "$TMPFILES_DIR"
echo "w $UART_DRIVER/unbind - - - - $UART_DEVICE" > "$TMPFILES_DIR/pifire-serial.conf"
if [[ -e "$UART_DRIVER/$UART_DEVICE" ]]; then
	echo "$UART_DEVICE" > "$UART_DRIVER/unbind"
fi
echo "Console seriale spenta in $ENV_FILE (console=none, extraargs console=tty1; backup in $ENV_FILE.pifire.bak), UART0 staccata dai pin 8 e 10: serve un riavvio"
exit 0
