'''
auto-install/orangepi/pifire-wait-online.sh: with NetworkManager running the
network, systemd-networkd-wait-online timed out at every boot (20 s and a red
FAILED on the display, board 2026-11-17).  The script disables it only when
NetworkManager is active and systemd-networkd manages no link.
System tools are replaced by stubs that only record their calls.
'''

import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'auto-install', 'orangepi', 'pifire-wait-online.sh')

# networkctl list --no-legend, as on the board
NM_LINKS = '''  1 lo    loopback carrier     unmanaged
  2 eth0  ether    no-carrier  unmanaged
  3 wlan0 wlan     routable    unmanaged
'''
NETWORKD_LINKS = '''  1 lo    loopback carrier     unmanaged
  2 eth0  ether    no-carrier  configuring
  3 wlan0 wlan     routable    configured
'''


def _run(tmp_path, nm_active=True, enabled=True, links=NM_LINKS):
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()
	calls = tmp_path / 'calls.log'
	(tmp_path / 'links.txt').write_text(links)
	stubs = {
		'systemctl': f'''echo "systemctl $*" >> {calls}
case "$*" in
	"is-active --quiet NetworkManager") exit {0 if nm_active else 3};;
	"is-enabled --quiet systemd-networkd-wait-online.service") exit {0 if enabled else 1};;
esac
exit 0''',
		'networkctl': f'cat {tmp_path / "links.txt"}',
	}
	for name, body in stubs.items():
		path = bin_dir / name
		path.write_text(f'#!/bin/sh\n{body}\n')
		path.chmod(0o755)
	env = dict(os.environ, PATH=f'{bin_dir}:/usr/bin:/bin')
	out = subprocess.run(['bash', SCRIPT], env=env, check=True, capture_output=True, text=True).stdout
	return out, calls.read_text().splitlines()


def _disabled(calls):
	return 'systemctl disable systemd-networkd-wait-online.service' in calls


def test_disabled_when_networkmanager_owns_every_link(tmp_path):
	out, calls = _run(tmp_path)
	assert _disabled(calls)
	assert 'disattivato' in out


def test_kept_while_networkd_still_manages_links(tmp_path):
	out, calls = _run(tmp_path, links=NETWORKD_LINKS)
	assert not _disabled(calls)
	assert 'eth0' in out and 'wlan0' in out


def test_kept_without_networkmanager(tmp_path):
	_, calls = _run(tmp_path, nm_active=False)
	assert not _disabled(calls)


def test_nothing_to_do_when_already_disabled(tmp_path):
	out, calls = _run(tmp_path, enabled=False)
	assert not _disabled(calls)
	assert 'già disattivato' in out
