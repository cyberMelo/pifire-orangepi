'''
auto-install/orangepi/pifire-console.sh: the HDMI display module draws in the
framebuffer of the Linux console, so the tty1 login prompt and the console
cursor would show over the PiFire screens (board, 2026-11-17).  The script
removes the login and turns the cursor off at every boot.
System tools are replaced by stubs that only record their calls.
'''

import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'auto-install', 'orangepi', 'pifire-console.sh')


def _run(tmp_path, getty_enabled=True):
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()
	calls = tmp_path / 'calls.log'
	stubs = {
		'systemctl': f'''echo "systemctl $*" >> {calls}
case "$*" in
	"is-enabled --quiet getty@tty1.service"|"is-active --quiet getty@tty1.service") exit {0 if getty_enabled else 1};;
esac
exit 0''',
		'systemd-tmpfiles': f'echo "systemd-tmpfiles $*" >> {calls}',
	}
	for name, body in stubs.items():
		path = bin_dir / name
		path.write_text(f'#!/bin/sh\n{body}\n')
		path.chmod(0o755)
	tmpfiles = tmp_path / 'tmpfiles.d'
	env = dict(os.environ, TMPFILES_DIR=str(tmpfiles), PATH=f'{bin_dir}:/usr/bin:/bin')
	out = subprocess.run(['bash', SCRIPT], env=env, check=True, capture_output=True, text=True).stdout
	return out, calls.read_text().splitlines(), tmpfiles


def test_removes_the_tty1_login_and_turns_the_cursor_off(tmp_path):
	out, calls, tmpfiles = _run(tmp_path)
	assert 'systemctl disable --now getty@tty1.service' in calls
	conf = tmpfiles / 'pifire-console.conf'
	assert conf.read_text().strip() == 'w /sys/class/graphics/fbcon/cursor_blink - - - - 0'
	assert f'systemd-tmpfiles --create {conf}' in calls
	assert 'login su tty1 tolto' in out


def test_idempotent(tmp_path):
	out, calls, tmpfiles = _run(tmp_path, getty_enabled=False)
	assert not any('disable' in l for l in calls)
	assert 'già tolto' in out
	assert (tmpfiles / 'pifire-console.conf').exists()
