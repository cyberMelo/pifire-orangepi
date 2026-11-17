'''
auto-install/orangepi/pifire-serial-console.sh: Armbian's boot.cmd adds
console=ttyS0 for console=display too, so setup.sh step 4 left the serial
console on pins 8 and 10 (the encoder) and systemd started a serial login on it
again (board, 2026-11-17).  The script sets a console value boot.cmd ignores
and puts the kernel console on tty1 through extraargs.
'''

import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'auto-install', 'orangepi', 'pifire-serial-console.sh')

BOARD_ENV = '''verbosity=1
bootlogo=false
console=display
disp_mode=1920x1080p60
overlay_prefix=sun50i-h616
overlays=i2c1-pi spidev1_0
'''

# The console lines of Armbian's boot.cmd for the Zero 2W (/boot/boot.cmd on the board)
BOOT_CMD = {
	'display': 'console=ttyS0,115200 console=tty1',
	'both': 'console=ttyS0,115200 console=tty1',
	'serial': 'console=ttyS0,115200',
}


def _run(tmp_path, text):
	env_file = tmp_path / 'armbianEnv.txt'
	env_file.write_text(text)
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()
	calls = tmp_path / 'calls.log'
	stub = bin_dir / 'systemctl'
	stub.write_text(f'#!/bin/sh\necho "systemctl $*" >> {calls}\n')
	stub.chmod(0o755)
	driver = tmp_path / 'dw-apb-uart'
	(driver / '5000000.serial').mkdir(parents=True, exist_ok=True)   # UART0 bound to its driver
	(driver / 'unbind').write_text('')
	env = _env(tmp_path)
	subprocess.run(['bash', SCRIPT, str(env_file)], env=env, check=True, capture_output=True)
	return env_file, calls.read_text().splitlines()


def _env(tmp_path):
	return dict(os.environ, PATH=f'{tmp_path / "bin"}:/usr/bin:/bin', TMPFILES_DIR=str(tmp_path / 'tmpfiles.d'),
				UART_DRIVER=str(tmp_path / 'dw-apb-uart'))


def kernel_consoles(env_text):
	''' The console= arguments boot.cmd would pass to the kernel '''
	values = dict(line.split('=', 1) for line in env_text.splitlines() if '=' in line)
	args = BOOT_CMD.get(values.get('console', 'both'), '') + ' ' + values.get('extraargs', '')
	return re.findall(r'console=(\S+)', args)


def test_display_still_meant_the_serial_console():
	assert 'ttyS0,115200' in kernel_consoles(BOARD_ENV)


def test_kernel_console_only_on_the_screen(tmp_path):
	env_file, calls = _run(tmp_path, BOARD_ENV)
	text = env_file.read_text()
	assert kernel_consoles(text) == ['tty1']
	assert 'overlays=i2c1-pi spidev1_0' in text and 'disp_mode=1920x1080p60' in text   # the rest stays
	assert (tmp_path / 'armbianEnv.txt.pifire.bak').read_text() == BOARD_ENV
	assert 'systemctl disable --now serial-getty@ttyS0.service' in calls


def test_existing_extraargs_are_kept_and_not_duplicated(tmp_path):
	env_file, _ = _run(tmp_path, BOARD_ENV + 'extraargs=video=HDMI-A-1:1024x600@60\n')
	assert 'extraargs=video=HDMI-A-1:1024x600@60 console=tty1' in env_file.read_text()
	# run again (setup.sh run twice): nothing added
	subprocess.run(['bash', SCRIPT, str(env_file)], env=_env(tmp_path), check=True, capture_output=True)
	assert env_file.read_text().count('console=tty1') == 1
	assert kernel_consoles(env_file.read_text()) == ['tty1']
	assert 'console=display' in (tmp_path / 'armbianEnv.txt.pifire.bak').read_text()   # the original backup stays


def test_uart0_lets_go_of_the_encoder_pins_now_and_at_boot(tmp_path):
	''' Without a console the UART0 driver still held PH0/PH1 (gpioinfo: consumer=kernel) '''
	_run(tmp_path, BOARD_ENV)
	assert (tmp_path / 'dw-apb-uart' / 'unbind').read_text().strip() == '5000000.serial'
	conf = (tmp_path / 'tmpfiles.d' / 'pifire-serial.conf').read_text().strip()
	assert conf == f'w {tmp_path / "dw-apb-uart"}/unbind - - - - 5000000.serial'


def test_file_without_console_line(tmp_path):
	env_file, _ = _run(tmp_path, 'verbosity=1\n')
	assert kernel_consoles(env_file.read_text()) == ['tty1']
