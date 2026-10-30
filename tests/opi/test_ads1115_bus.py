'''
ADS1115 on the Orange Pi Zero 2W: the header I2C bus is looked up from the
controller address (on the real board: /dev/i2c-2, while i2c-1 is HDMI), and
the module reads the chip directly with smbus2.
'''

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from probes.i2c_bus import header_i2c_bus  # noqa: E402
from probes import ads1115  # noqa: E402


def fake_sysfs(tmp_path):
	''' Same layout the board reported (opi readlink output, 2026-10-30) '''
	platform = tmp_path / 'devices' / 'platform' / 'soc'
	links = tmp_path / 'bus'
	links.mkdir()
	for number, controller in ((0, '7081400.i2c'), (1, '6000000.hdmi'), (2, '5002400.i2c')):
		target = platform / controller / f'i2c-{number}'
		target.mkdir(parents=True)
		os.symlink(target, links / f'i2c-{number}')
	return str(links)


def test_header_bus_is_found_by_controller(tmp_path):
	sysfs = fake_sysfs(tmp_path)
	assert header_i2c_bus('auto', sysfs=sysfs) == 2
	assert header_i2c_bus(None, sysfs=sysfs) == 2
	assert header_i2c_bus('3', sysfs=sysfs) == 3          # set by hand in the device config
	assert header_i2c_bus('auto', sysfs=str(tmp_path / 'none')) == 1   # unknown board: Raspberry layout


class FakeADS1115:
	''' Registers of an ADS1115 that converts instantly; channel n reads volts[n] '''
	def __init__(self, bus_number, volts=(1.0, 2.5, 0.0, -0.1)):
		self.bus_number, self.volts, self.config = bus_number, volts, 0
		self.writes = []

	def write_i2c_block_data(self, address, register, data):
		assert address == 0x48 and register == 0x01
		self.config = (data[0] << 8) | data[1]
		self.writes.append(self.config)

	def read_i2c_block_data(self, address, register, length):
		if register == 0x01:
			return [0x80 | (self.config >> 8) & 0x7F, self.config & 0xFF]   # conversion done
		channel = ((self.config >> 12) & 0x7) - 4
		raw = int(round(self.volts[channel] * 1000 / 6144.0 * 32768)) & 0xFFFF
		return [raw >> 8, raw & 0xFF]


def test_reads_millivolts_on_the_header_bus(tmp_path, monkeypatch):
	sysfs = fake_sysfs(tmp_path)
	monkeypatch.setattr(ads1115, 'header_i2c_bus', lambda configured=None: header_i2c_bus(configured, sysfs=sysfs))
	device = ads1115.ADSDevice(i2c_bus_addr=0x48, i2c_bus='auto', smbus=FakeADS1115)
	assert device.bus.bus_number == 2 and device.get_status()['i2c_bus'] == 2
	assert abs(device.read_voltage('ADC0') - 1000) < 0.5
	assert abs(device.read_voltage('ADC1') - 2500) < 0.5
	assert abs(device.read_voltage('ADC3') + 100) < 0.5        # negative values keep their sign
	# single-shot, +/-6.144 V, 128 SPS, AIN1 against GND
	assert device.bus.writes[1] == 0x8000 | 0x5000 | 0x0100 | 0x0080 | 0x0003


def test_read_error_gives_zero(monkeypatch):
	class Broken(FakeADS1115):
		def write_i2c_block_data(self, *args):
			raise OSError(121, 'Remote I/O error')
	device = ads1115.ADSDevice(i2c_bus='2', smbus=Broken)
	assert device.read_voltage('ADC0') == 0
