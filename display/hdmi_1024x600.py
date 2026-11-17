'''
*****************************************
PiFire HDMI 5" display (1024x600, touch and encoder)
*****************************************

Display module for the MPI5006 HDMI display of the Orange Pi fork, without a
desktop and without new libraries:

  - screens drawn with Pillow (display/hdmi_ui.py) and copied to the Linux
    framebuffer /dev/fb0 (group video);
  - touch read from /dev/input/event* (group input), the USB touch screen;
  - KY-040 encoder on the PCB v4 input pins (CLK/DT/SW) through libgpiod;
  - data read from Redis like the web app, commands sent with the same API
    commands (display/hdmi_state.py).

Everything runs in a separate process: a display problem never stops the
control loop.  The encoder pins 8 and 10 are the serial console on the Zero 2W:
with the console active the encoder is skipped and the touch still works.
'''

import fcntl
import glob
import logging
import multiprocessing
import os
import queue
import struct
import threading
import time

PX_W, PX_H = 1024, 600

'''
==============================
  Framebuffer
==============================
'''

class FrameBuffer:
	''' The Linux framebuffer: a PIL image becomes the pixels of the screen '''

	def __init__(self, device='/dev/fb0', sysfs=None):
		self.device = device
		sysfs = sysfs or f'/sys/class/graphics/{os.path.basename(device)}'
		read = lambda name: open(os.path.join(sysfs, name)).read().strip()
		self.width, self.height = (int(v) for v in read('virtual_size').split(','))
		self.bpp = int(read('bits_per_pixel'))
		self.stride = int(read('stride'))
		if self.bpp != 32:   # sun4i-drm on the Zero 2W: XRGB8888
			raise RuntimeError(f'Unsupported framebuffer format: {self.bpp} bits per pixel (32 expected)')
		self.fd = os.open(device, os.O_RDWR)

	def frame(self, img):
		''' Bytes for the framebuffer: XRGB8888, little endian (B, G, R, X) '''
		if img.size != (self.width, self.height):
			from PIL import Image
			canvas = Image.new('RGB', (self.width, self.height))
			canvas.paste(img, (0, 0))
			img = canvas
		data = img.convert('RGB').tobytes('raw', 'BGRX')
		row = self.width * self.bpp // 8
		if self.stride == row:
			return data
		pad = b'\x00' * (self.stride - row)
		return b''.join(data[i:i + row] + pad for i in range(0, len(data), row))

	def show(self, img):
		os.pwrite(self.fd, self.frame(img), 0)

	def close(self):
		os.close(self.fd)


'''
==============================
  Touch screen (evdev)
==============================
'''

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH = 0x14a
ABS_X, ABS_Y, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x00, 0x01, 0x35, 0x36
EVENT = struct.Struct('llHHi')   # struct input_event on 64-bit Linux


def find_touch_device(root='/sys/class/input'):
	''' /dev/input/eventN of the first device whose name says touch screen '''
	for path in sorted(glob.glob(os.path.join(root, 'event*'))):
		try:
			name = open(os.path.join(path, 'device', 'name')).read().strip()
		except OSError:
			continue
		if 'touch' in name.lower():
			return f'/dev/input/{os.path.basename(path)}', name
	return None, None


def abs_range(fd, code):
	''' (min, max) of an absolute axis: ioctl EVIOCGABS, struct input_absinfo (6 x int32) '''
	request = (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code)   # _IOR('E', 0x40 + code, 24 bytes)
	info = struct.unpack('6i', fcntl.ioctl(fd, request, b'\x00' * 24))
	return info[1], info[2]


class TouchDecoder:
	''' Raw touch events -> taps in screen pixels (a tap = finger lifted) '''

	def __init__(self, x_range, y_range, width=PX_W, height=PX_H):
		self.x_range, self.y_range = x_range, y_range
		self.width, self.height = width, height
		self.x = self.y = None
		self.down = False

	@staticmethod
	def _scale(value, rng, size):
		lo, hi = rng
		return max(0, min(size - 1, int((value - lo) * size / max(1, hi - lo + 1))))

	def feed(self, ev_type, code, value):
		if ev_type == EV_ABS and code in (ABS_X, ABS_MT_POSITION_X):
			self.x = self._scale(value, self.x_range, self.width)
		elif ev_type == EV_ABS and code in (ABS_Y, ABS_MT_POSITION_Y):
			self.y = self._scale(value, self.y_range, self.height)
		elif ev_type == EV_KEY and code == BTN_TOUCH:
			if value:
				self.down = True
			elif self.down:
				self.down = False
				if self.x is not None and self.y is not None:
					return ('tap', self.x, self.y)
		return None


def touch_thread(events, log):
	device, name = find_touch_device()
	if not device:
		log.info('HDMI display: no touch screen found')
		return
	try:
		fd = os.open(device, os.O_RDONLY)
		decoder = TouchDecoder(abs_range(fd, ABS_X), abs_range(fd, ABS_Y))
	except OSError as error:
		log.error(f'HDMI display: cannot open the touch screen {device} ({name}): {error}')
		return
	log.info(f'HDMI display: touch screen {name} on {device}')
	while True:
		data = os.read(fd, EVENT.size * 64)
		for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
			_, _, ev_type, code, value = EVENT.unpack_from(data, i)
			tap = decoder.feed(ev_type, code, value)
			if tap:
				events.put(tap)


'''
==============================
  Encoder (KY-040)
==============================
'''

# Quadrature: (previous CLK,DT state << 2 | new state) -> +1 / -1 / 0
_QUAD = {0b0001: -1, 0b0010: 1, 0b0100: 1, 0b0111: -1, 0b1000: -1, 0b1011: 1, 0b1101: 1, 0b1110: -1}


class EncoderDecoder:
	''' CLK/DT samples -> detents (a KY-040 detent is a full cycle of 4 transitions) '''

	TRANSITIONS_PER_DETENT = 4

	def __init__(self, clk=1, dt=1):
		self.state = (clk << 1) | dt
		self.count = 0

	def feed(self, clk, dt):
		new = (int(clk) << 1) | int(dt)
		if new == self.state:
			return 0
		self.count += _QUAD.get((self.state << 2) | new, 0)
		self.state = new
		if new == 0b11 and abs(self.count) >= self.TRANSITIONS_PER_DETENT - 1:   # back at rest: one detent
			step = 1 if self.count > 0 else -1
			self.count = 0
			return step
		if new == 0b11:
			self.count = 0
		return 0


class ButtonDebouncer:
	def __init__(self, ms=40):
		self.ms = ms
		self.pressed = False
		self.since = 0.0

	def feed(self, active, now):
		''' True once per press, after the contact has been stable for ms '''
		if active == self.pressed:
			self.since = now
			return False
		if (now - self.since) * 1000 >= self.ms:
			self.pressed = active
			self.since = now
			return active
		return False


def encoder_thread(events, pins, log):
	try:
		from grillplat.opi_gpio import Button
		clk, dt, sw = (Button(pins[name]) for name in ('up_clk', 'down_dt', 'enter_sw'))
	except Exception as error:
		log.warning(f'HDMI display: encoder not available ({error}); is the serial console still on pins 8 and 10?')
		return
	log.info('HDMI display: encoder on GPIO %s/%s/%s' % (pins['up_clk'], pins['down_dt'], pins['enter_sw']))
	# Button.is_active is True when the pin is pulled to ground; the decoder wants the pin level
	decoder = EncoderDecoder(int(not clk.is_active), int(not dt.is_active))
	button = ButtonDebouncer()
	while True:
		step = decoder.feed(int(not clk.is_active), int(not dt.is_active))
		if step:
			events.put(('rotate', step))
		if button.feed(sw.is_active, time.monotonic()):
			events.put(('press',))
		time.sleep(0.001)


'''
==============================
  Display process
==============================
'''

def _start_thread(target, *args):
	thread = threading.Thread(target=target, args=args, daemon=True)
	thread.start()
	return thread


class DataSource:
	''' What the screens need, read from Redis at the pace each part changes '''

	PERIODS = {'fast': 1.0, 'control': 2.0, 'wifi': 5.0, 'history': 30.0}

	def __init__(self, probes):
		self.probes = probes
		self.data = {'probes': probes}
		self.next = {name: 0.0 for name in self.PERIODS}

	def refresh(self, now, force=False):
		from common.common import read_current, read_status, read_control, read_history
		from blueprints.dash.modern_data import downsample_history, timer_state, HISTORY_POINTS_PER_MINUTE
		from display.hdmi_state import GRAPH_MINUTES
		due = lambda name: force or now >= self.next[name]
		if due('fast'):
			self.data['current'] = read_current()
			self.data['status'] = read_status()
			self.next['fast'] = now + self.PERIODS['fast']
		if due('control'):
			control = read_control()
			self.data['notify'] = control.get('notify_data', [])
			self.data['timer'] = timer_state(control.get('timer'), control.get('notify_data'), now)
			self.next['control'] = now + self.PERIODS['control']
		if due('wifi'):
			from wifi.state import RedisStore, service_running
			status = RedisStore().read_status()
			self.data['wifi'] = status if service_running(status, now) else None
			self.next['wifi'] = now + self.PERIODS['wifi']
		if due('history'):
			history = read_history(num_items=GRAPH_MINUTES * HISTORY_POINTS_PER_MINUTE)
			self.data['history'] = downsample_history(history, max_points=180)
			self.next['history'] = now + self.PERIODS['history']
		return self.data


def run(units, probes, presets, pins, messages, parent_pid):
	from common.common import process_command
	from display.hdmi_state import Ui
	from display.hdmi_ui import Renderer
	log = logging.getLogger('control')
	try:
		fb = FrameBuffer()
	except (OSError, RuntimeError) as error:
		log.error(f'HDMI display: framebuffer not available ({error})')
		return
	events = queue.Queue()
	_start_thread(touch_thread, events, log)
	_start_thread(encoder_thread, events, pins, log)
	ui = Ui(units, presets)
	renderer = Renderer()
	source = DataSource(probes)
	last_view, last_draw, force = None, 0.0, True
	while os.getppid() == parent_pid:   # the control process is gone: stop drawing and free the pins
		now = time.time()
		try:
			while True:
				ui.show_message(messages.get_nowait(), now)
		except queue.Empty:
			pass
		try:
			data = source.refresh(now, force)
			force = False
			try:
				event = events.get(timeout=0.2)
			except queue.Empty:
				event = None
			commands = []
			if event:
				now = time.time()
				if event[0] == 'tap':
					commands = ui.touch(event[1], event[2], data, now)
				elif event[0] == 'rotate':
					commands = ui.rotate(event[1], data, now)
				elif event[0] == 'press':
					commands = ui.press(data, now)
			for action, arglist in commands:
				result = process_command(action=action, arglist=arglist, origin='display')
				log.info(f'HDMI display: {action} {"/".join(a for a in arglist if a)} -> {result.get("result")}')
				force = True
			view = ui.view(data, now)
			if view != last_view or now - last_draw > 30:
				fb.show(renderer.render(view))
				last_view, last_draw = view, now
		except Exception:
			log.exception('HDMI display: error in the display loop')
			time.sleep(2)
	fb.close()


class Display:
	''' The interface control.py expects from a display module '''

	def __init__(self, dev_pins, buttonslevel='HIGH', rotation=0, units='F', config={}):
		from display.hdmi_state import parse_presets
		from common.common import read_settings
		settings = read_settings()
		modern = settings.get('dashboard', {}).get('dashboards', {}).get('Modern', {}).get('config', {})
		units = units if units in ('C', 'F') else 'C'
		self.messages = multiprocessing.Queue()
		self.process = multiprocessing.Process(
			target=run, daemon=True,
			args=(units, config.get('probe_info', {}), parse_presets(modern.get('presets'), units),
				  dev_pins.get('input', {}), self.messages, os.getpid()))
		self.process.start()

	def display_status(self, in_data, status_data):
		pass   # the display process reads the same data from Redis

	def display_splash(self):
		pass

	def clear_display(self):
		pass

	def display_text(self, text):
		labels = {'ERROR': 'ERRORE', 'Re-Ignite': 'RIACCENSIONE'}
		self.messages.put(labels.get(text, text))

	def display_network(self):
		pass
