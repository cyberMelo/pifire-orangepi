#!/usr/bin/env python3

'''
*****************************************
PiFire Probes ADS1115 Module 
*****************************************

Description: 
  This module utilizes the ADS1115 hardware and returns temperature data.
  Orange Pi fork: talks to the chip with smbus2 on the header I2C bus.
	
	Ex Device Definition: 
	
	device = {
			'device' : 'your_device_name',	# Unique name for the device
			'module' : 'ads1115',  			# Must be populated for this module to load properly
			'ports' : ['ADC0', 'ADC1', 'ADC2', 'ADC3'], # This is defined in the module, so this does not need to be defined.
			'config' : {
				'ADC0_rd': '10000',
            	'ADC1_rd': '10000',
            	'ADC2_rd': '10000',
            	'ADC3_rd': '10000',
            	'i2c_bus_addr': '0x48',
            	'i2c_bus': 'auto',  # or the /dev/i2c-N number
            	'voltage_ref': '3.28'
			} 
		}
'''

'''
*****************************************
 Imported Libraries
*****************************************
'''
import logging
import time
from probes.base import ProbeInterface
from probes.i2c_bus import header_i2c_bus

'''
*****************************************
 Class Definitions 
*****************************************
'''

BUSMAP = {
	'0x48' : 0x48,  # Address Pin GND
	'0x49' : 0x49,  # Address Pin VIN 
	'0x4A' : 0x4A,	# Address Pin SDA
	'0x4B' : 0x4B	# Address Pin SCL
}

# ADS1115 registers and configuration (datasheet SBAS444)
REG_CONVERSION = 0x00
REG_CONFIG = 0x01
OS_START = 0x8000            # write: start a single conversion; read: 1 = conversion done
MUX_SINGLE = (0x4000, 0x5000, 0x6000, 0x7000)   # AINx against GND
PGA_6_144V = 0x0000          # +/-6.144 V full scale (same range as the Adafruit module, gain 2/3)
MODE_SINGLE = 0x0100
DR_128SPS = 0x0080
COMP_DISABLE = 0x0003
FULL_SCALE_MV = 6144.0


class ADSDevice():
	'''
	ADS1115 read directly over I2C with smbus2 (Orange Pi fork).

	The upstream module used the "ADS1115" package, which always opens
	/dev/i2c-1: on the Orange Pi Zero 2W that is the HDMI bus.  This version
	opens the header bus (see probes/i2c_bus.py) or the one set in the device
	config ('i2c_bus').
	'''
	def __init__(self, i2c_bus_addr=0x48, i2c_bus=None, smbus=None):
		self.logger = logging.getLogger("control")
		self.address = i2c_bus_addr
		self.bus_number = header_i2c_bus(i2c_bus)
		if smbus is None:
			from smbus2 import SMBus
			smbus = SMBus
		self.bus = smbus(self.bus_number)
		self.logger.debug(f'ADS1115 at {hex(self.address)} on /dev/i2c-{self.bus_number}')
		self.status = {'i2c_bus': self.bus_number}

	def _read_mv(self, channel):
		config = OS_START | MUX_SINGLE[channel] | PGA_6_144V | MODE_SINGLE | DR_128SPS | COMP_DISABLE
		self.bus.write_i2c_block_data(self.address, REG_CONFIG, [(config >> 8) & 0xFF, config & 0xFF])
		# 128 samples/s: a conversion takes ~7.8 ms; wait for the "done" bit (at most ~25 ms)
		deadline = time.monotonic() + 0.025
		time.sleep(0.008)
		while time.monotonic() < deadline:
			high, _ = self.bus.read_i2c_block_data(self.address, REG_CONFIG, 2)
			if high & 0x80:
				break
			time.sleep(0.001)
		high, low = self.bus.read_i2c_block_data(self.address, REG_CONVERSION, 2)
		value = (high << 8) | low
		if value & 0x8000:
			value -= 1 << 16
		return value * FULL_SCALE_MV / 32768.0

	def read_voltage(self, port):
		adc_ports = {
			'ADC0' : 0, 
			'ADC1' : 1, 
			'ADC2' : 2, 
			'ADC3' : 3
		}
		try:
			voltage = self._read_mv(adc_ports[port])
		except Exception:
			self.logger.exception(f'Exception occurred while reading probe port {port}.  Trace dump: ')
			voltage = 0
		return voltage

	def get_status(self):
		return self.status

class ReadProbes(ProbeInterface):

	def __init__(self, probe_info, device_info, units):
		super().__init__(probe_info, device_info, units)

	def _init_device(self):
		self.time_delay = 0
		self.device_info['ports'] = ['ADC0', 'ADC1', 'ADC2', 'ADC3']
		i2c_bus_addr = BUSMAP[self.device_info['config'].get('i2c_bus_addr', '0x48')]
		self.device = ADSDevice(i2c_bus_addr=i2c_bus_addr, i2c_bus=self.device_info['config'].get('i2c_bus', 'auto'))
