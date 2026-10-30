'''
auto-install/orangepi/pifire-devices.sh: on Armbian /dev/gpiochip* and
/dev/spidev* are root-only, so PiFire (running as a normal user) found no GPIO
chip and fell back to the simulated platform (board test, 2026-10-30).  The
script installs a udev rule for the gpio/spi groups and adds the user to them.
System tools are replaced by stubs that only record their calls.
'''

import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'auto-install', 'orangepi', 'pifire-devices.sh')
RULES = os.path.join(ROOT, 'auto-install', 'orangepi', '60-pifire-devices.rules')


def _stub_bin(tmp_path, existing_groups):
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()
	calls = tmp_path / 'calls.log'
	stubs = {
		'getent': f'echo "getent $*" >> {calls}; case " {" ".join(existing_groups)} " in *" $2 "*) exit 0;; esac; exit 2',
		'id': f'echo "id $*" >> {calls}; exit 0',
		'groupadd': f'echo "groupadd $*" >> {calls}',
		'usermod': f'echo "usermod $*" >> {calls}',
		'udevadm': f'echo "udevadm $*" >> {calls}',
	}
	for name, body in stubs.items():
		path = bin_dir / name
		path.write_text(f'#!/bin/sh\n{body}\n')
		path.chmod(0o755)
	return bin_dir, calls


def test_rule_gives_gpio_and_spi_to_their_groups():
	rules = [l for l in open(RULES).read().splitlines() if l and not l.startswith('#')]
	assert 'SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"' in rules
	assert 'SUBSYSTEM=="spidev", KERNEL=="spidev*", GROUP="spi", MODE="0660"' in rules


def test_installs_rule_groups_and_reloads_udev(tmp_path):
	bin_dir, calls = _stub_bin(tmp_path, existing_groups=['gpio', 'i2c'])
	udev = tmp_path / 'rules.d'
	env = dict(os.environ, UDEV_DIR=str(udev), PATH=f'{bin_dir}:/usr/bin:/bin')
	subprocess.run(['bash', SCRIPT, 'pifire'], env=env, check=True, capture_output=True)
	assert (udev / '60-pifire-devices.rules').read_text() == open(RULES).read()
	log = calls.read_text().splitlines()
	assert 'groupadd --system spi' in log and not any('groupadd --system gpio' in l for l in log)
	for group in ('gpio', 'spi', 'i2c'):
		assert f'usermod -a -G {group} pifire' in log
	assert any(l.startswith('udevadm trigger') and 'gpio' in l for l in log)


def test_root_is_not_added_to_groups(tmp_path):
	bin_dir, calls = _stub_bin(tmp_path, existing_groups=['gpio', 'spi', 'i2c'])
	env = dict(os.environ, UDEV_DIR=str(tmp_path / 'rules.d'), PATH=f'{bin_dir}:/usr/bin:/bin')
	subprocess.run(['bash', SCRIPT, 'root'], env=env, check=True, capture_output=True)
	assert not any(l.startswith('usermod') for l in calls.read_text().splitlines())
