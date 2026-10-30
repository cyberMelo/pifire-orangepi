'''
Which /dev/i2c-N is the I2C bus on the 40-pin header (pins 3 and 5).

Orange Pi fork.  On the Raspberry Pi it is always bus 1, but on the Orange Pi
Zero 2W (Allwinner H618) the kernel numbers the buses in probe order: with
Armbian the header bus (controller TWI1 at 0x5002400, enabled by the i2c1-pi
overlay) came up as /dev/i2c-2, while /dev/i2c-1 was the HDMI DDC bus.  The
number is therefore looked up from the controller address, not assumed.
'''

import glob
import os

# I2C controllers that can drive header pins 3 and 5, by platform device name
HEADER_CONTROLLERS = (
	'5002400.i2c',  # Allwinner H616/H618 TWI1 (Orange Pi Zero 2W, overlay i2c1-pi)
)
DEFAULT_BUS = 1     # Raspberry Pi layout, last resort


def bus_controllers(sysfs='/sys/bus/i2c/devices'):
	''' {bus number: platform path} for every I2C adapter the kernel created '''
	buses = {}
	for path in glob.glob(os.path.join(sysfs, 'i2c-*')):
		name = os.path.basename(path)
		try:
			number = int(name.split('-', 1)[1])
		except ValueError:
			continue
		buses[number] = os.path.realpath(path)
	return buses


def header_i2c_bus(configured=None, sysfs='/sys/bus/i2c/devices'):
	'''
	Bus number for the header I2C pins.

	:param configured: value from the probe device config ('auto', '', None or a number)
	:return: int bus number
	'''
	if configured not in (None, '', 'auto'):
		return int(configured)
	for number, path in sorted(bus_controllers(sysfs).items()):
		if any(f'/{controller}/' in path + '/' for controller in HEADER_CONTROLLERS):
			return number
	return DEFAULT_BUS
