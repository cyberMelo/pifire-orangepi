'''
opi_check.py: HDMI mode and touch screen of the MPI5006 display (1024x600).
'''

import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_spec = importlib.util.spec_from_file_location('opi_check', os.path.join(ROOT, 'auto-install', 'orangepi', 'opi_check.py'))
opi_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(opi_check)


def test_hdmi_connectors(tmp_path):
	card = tmp_path / 'card0-HDMI-A-1'
	card.mkdir()
	(card / 'status').write_text('connected\n')
	(card / 'modes').write_text('1024x600\n800x600\n640x480\n')
	(tmp_path / 'card0-HDMI-A-2').mkdir()
	(tmp_path / 'card0-HDMI-A-2' / 'status').write_text('disconnected\n')
	result = opi_check.hdmi_connectors(str(tmp_path))
	assert result[0] == ('card0-HDMI-A-1', 'connected', ['1024x600', '800x600', '640x480'])
	assert result[1] == ('card0-HDMI-A-2', 'disconnected', [])
	assert opi_check.DISPLAY_MODE == '1024x600'


def test_touch_devices(tmp_path):
	devices = tmp_path / 'devices'
	devices.write_text('I: Bus=0003\nN: Name="wch.cn USB2IIC_CTP_CONTROL"\n\n'
					   'I: Bus=0003\nN: Name="ILITEK ILITEK-TOUCH"\n\nN: Name="gpio-keys"\n')
	assert opi_check.touch_devices(str(devices)) == ['wch.cn USB2IIC_CTP_CONTROL', 'ILITEK ILITEK-TOUCH']


def test_gpio_consumers_in_both_gpioinfo_formats():
	''' Board, 2026-11-18: libgpiod tools v2 print consumer=pifire, so the
	encoder pins held by PiFire were not reported as busy '''
	v2 = ('gpiochip1 - 288 lines:\n'
		  '\tline  75:\tunnamed         \tinput\n'
		  '\tline  76:\tunnamed         \tinput active-low bias=pull-up consumer=pifire\n'
		  '\tline 224:\t"PH0"           \tinput consumer="kernel x"\n')
	assert opi_check.gpio_consumers(v2) == {76: 'pifire', 224: 'kernel x'}
	v1 = ('\tline  76:      unnamed   "pifire"   input  active-low [used]\n'
		  '\tline  77:      "PC13"    unused     input  active-high\n'
		  '\tline 224:      "PH0"     "kernel"   input  active-high [used]\n')
	assert opi_check.gpio_consumers(v1) == {76: 'pifire', 224: 'kernel'}


def test_serial_console_note_only_while_the_console_is_on(tmp_path):
	cmdline = tmp_path / 'cmdline'
	cmdline.write_text('root=UUID=x rootwait console=tty1 cgroup_enable=memory\n')
	assert not opi_check.serial_console_on(str(cmdline))
	cmdline.write_text('root=UUID=x console=ttyS0,115200 console=tty1\n')
	assert opi_check.serial_console_on(str(cmdline))
