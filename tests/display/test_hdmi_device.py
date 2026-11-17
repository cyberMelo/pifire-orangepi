'''
HDMI 5" display (display/hdmi_1024x600.py): framebuffer pixel format, touch
events from /dev/input and the KY-040 encoder, without the board.
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
Image = pytest.importorskip('PIL.Image')

from display import hdmi_1024x600 as dev   # noqa: E402


def _fb(tmp_path, width=4, height=2, bpp=32, stride=None):
	sysfs = tmp_path / 'fb0'
	sysfs.mkdir()
	(sysfs / 'virtual_size').write_text(f'{width},{height}\n')
	(sysfs / 'bits_per_pixel').write_text(f'{bpp}\n')
	(sysfs / 'stride').write_text(f'{stride or width * bpp // 8}\n')
	device = tmp_path / 'fb'
	device.write_bytes(b'\xff' * (stride or width * bpp // 8) * height)
	return dev.FrameBuffer(str(device), str(sysfs)), device


def test_framebuffer_gets_little_endian_xrgb(tmp_path):
	fb, device = _fb(tmp_path)
	img = Image.new('RGB', (4, 2), (10, 20, 30))
	img.putpixel((0, 0), (255, 0, 0))
	fb.show(img)
	fb.close()
	data = device.read_bytes()
	assert data[0:3] == bytes([0, 0, 255])        # red pixel: B, G, R
	assert data[4:7] == bytes([30, 20, 10])
	assert len(data) == 4 * 2 * 4


def test_framebuffer_pads_rows_to_the_stride(tmp_path):
	fb, _ = _fb(tmp_path, width=3, height=2, stride=16)
	frame = fb.frame(Image.new('RGB', (3, 2), (1, 2, 3)))
	fb.close()
	assert len(frame) == 32 and frame[12:16] == b'\x00' * 4 and frame[16:19] == bytes([3, 2, 1])


def test_framebuffer_refuses_other_formats(tmp_path):
	with pytest.raises(RuntimeError, match='16 bits'):
		_fb(tmp_path, width=1, height=1, bpp=16)


def test_touch_tap_is_reported_when_the_finger_lifts():
	t = dev.TouchDecoder((0, 4095), (0, 4095))
	assert t.feed(dev.EV_KEY, dev.BTN_TOUCH, 1) is None
	assert t.feed(dev.EV_ABS, dev.ABS_X, 2048) is None
	assert t.feed(dev.EV_ABS, dev.ABS_Y, 1024) is None
	assert t.feed(dev.EV_SYN, 0, 0) is None
	assert t.feed(dev.EV_KEY, dev.BTN_TOUCH, 0) == ('tap', 512, 150)
	assert t.feed(dev.EV_KEY, dev.BTN_TOUCH, 0) is None     # no second tap without a new touch


def test_touch_multitouch_coordinates_and_screen_edges():
	t = dev.TouchDecoder((0, 1023), (0, 599))
	t.feed(dev.EV_KEY, dev.BTN_TOUCH, 1)
	t.feed(dev.EV_ABS, dev.ABS_MT_POSITION_X, 5000)
	t.feed(dev.EV_ABS, dev.ABS_MT_POSITION_Y, -3)
	assert t.feed(dev.EV_KEY, dev.BTN_TOUCH, 0) == ('tap', 1023, 0)


def test_find_touch_device(tmp_path):
	for n, name in ((0, 'dw_hdmi'), (1, 'QDtech MPI5001 Touchscreen')):
		d = tmp_path / f'event{n}' / 'device'
		d.mkdir(parents=True)
		(d / 'name').write_text(name + '\n')
	assert dev.find_touch_device(str(tmp_path)) == ('/dev/input/event1', 'QDtech MPI5001 Touchscreen')
	assert dev.find_touch_device(str(tmp_path / 'missing')) == (None, None)


def _turn(decoder, states):
	return sum(decoder.feed(clk, dt) for clk, dt in states)


CW = [(0, 1), (0, 0), (1, 0), (1, 1)]
CCW = [(1, 0), (0, 0), (0, 1), (1, 1)]


def test_encoder_one_detent_per_cycle_both_ways():
	e = dev.EncoderDecoder()
	assert _turn(e, CW) == 1
	assert _turn(e, CW * 3) == 3
	assert _turn(e, CCW) == -1


def test_encoder_ignores_bounce_and_half_turns():
	e = dev.EncoderDecoder()
	assert _turn(e, [(0, 1), (1, 1), (0, 1), (1, 1)]) == 0       # contact bounce on CLK
	assert _turn(e, [(0, 1), (0, 0), (0, 1), (1, 1)]) == 0       # half a detent and back
	assert _turn(e, [(1, 1), (1, 1)]) == 0                       # no change
	assert _turn(e, CW) == 1                                     # still in step afterwards


def test_encoder_does_not_count_impossible_jumps():
	e = dev.EncoderDecoder()
	assert _turn(e, [(0, 1), (0, 0), (1, 1)]) == 0    # 00 -> 11 is invalid: not counted
	assert _turn(e, [(0, 1), (1, 0), (1, 1)]) == 0
	assert _turn(e, [(0, 1), (0, 0), (1, 0), (1, 1)]) == 1


def test_button_debounce():
	b = dev.ButtonDebouncer(ms=40)
	assert not b.feed(True, 0.000)
	assert not b.feed(False, 0.010)      # bounce
	assert not b.feed(True, 0.020)
	assert b.feed(True, 0.065)           # stable for 40 ms: one press
	assert not b.feed(True, 0.200)       # held: no repeat
	assert not b.feed(False, 0.300)
	assert not b.feed(False, 0.350)      # released
	assert b.feed(True, 0.360) is False and b.feed(True, 0.401)
