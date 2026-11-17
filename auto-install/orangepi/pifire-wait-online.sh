#!/usr/bin/env bash
#
# Boot-time wait for the network (Orange Pi fork).  Run as root:
#     bash pifire-wait-online.sh
# Where NetworkManager runs the network and systemd-networkd manages no link,
# systemd-networkd-wait-online can only time out: it holds the boot for 20 s and
# shows a red FAILED on the display (board, 2026-11-17).  NetworkManager-wait-online
# already provides network-online.target, so the networkd one is disabled.
# A board still run by systemd-networkd (Armbian Minimal before setup.sh step 7)
# keeps it.  Idempotent: setup.sh and the OTA updater (ota-system.sh) both run it.

set -u
UNIT=systemd-networkd-wait-online.service

if ! systemctl is-active --quiet NetworkManager; then
	echo "$UNIT lasciato com'è: NetworkManager non gestisce la rete"
	exit 0
fi
if ! systemctl is-enabled --quiet "$UNIT"; then
	echo "$UNIT già disattivato"
	exit 0
fi
# Links systemd-networkd manages (SETUP column other than "unmanaged"), loopback aside
MANAGED=$(networkctl list --no-legend 2>/dev/null | awk '$2 != "lo" && $NF != "unmanaged" {print $2}' | tr '\n' ' ')
if [[ -n "$MANAGED" ]]; then
	echo "$UNIT lasciato attivo: systemd-networkd gestisce ancora $MANAGED"
	exit 0
fi
systemctl disable "$UNIT" >/dev/null 2>&1
echo "$UNIT disattivato: la rete la gestisce NetworkManager"
exit 0
