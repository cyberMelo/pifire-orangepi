'''
HDMI 5" display (display/hdmi_ui.py): every screen draws at 1024x600 at the
speed the board needs (no oversampling), and the touch areas stay on screen.
'''

import os
import sys
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
pytest.importorskip('PIL')
pytest.importorskip('qrcode')

from display import hdmi_ui as ui   # noqa: E402


@pytest.mark.parametrize('name', sorted(ui.sample_views()))
def test_every_screen_renders(name):
	view = ui.sample_views()[name]
	img = ui.Renderer().render(view)
	assert img.size == (1024, 600) and img.mode == 'RGB'
	assert img.getpixel((0, 599)) == ui.BG            # background reaches the corners
	assert len(img.resize((64, 38)).getcolors(64 * 38)) > 4   # something is drawn


def test_fonts_and_icons_are_shipped():
	for name in ('Barlow-Medium.ttf', 'Barlow-SemiBold.ttf', 'BarlowCondensed-Medium.ttf', 'BarlowCondensed-SemiBold.ttf', 'OFL.txt'):
		assert os.path.exists(os.path.join(ui.FONTS, name))
	assert os.path.exists(ui.FA)


def test_touch_areas_are_on_screen_and_cover_every_button():
	views = ui.sample_views()
	for view in views.values():
		for name, (x0, y0, x1, y1) in ui.targets(view):
			assert 0 <= x0 < x1 <= ui.PX_W and 0 <= y0 < y1 <= ui.PX_H, (view['screen'], name)
	names = lambda v: [n for n, _ in ui.targets(v)]
	assert {'preset:0', 'preset:3', 'confirm', 'back', 'dial'} <= set(names(views['setpoint']))
	assert {f'item:{i}' for i in range(4)} <= set(names(views['menu']))
	assert {'ok', 'cancel'} == set(names(views['confirm']))


def test_dial_angles():
	view = ui.sample_views()['setpoint']
	cx, cy, r = ui.DIAL
	at = lambda deg: (int((cx + r * ui.math.cos(ui.math.radians(deg))) * ui.DS), int((cy + r * ui.math.sin(ui.math.radians(deg))) * ui.DS))
	assert ui.dial_value(view, *at(136)) == pytest.approx(view['vmin'], abs=2)     # start of the arc (bottom left)
	assert ui.dial_value(view, *at(404)) == pytest.approx(view['vmax'], abs=2)     # end (bottom right)
	assert ui.dial_value(view, *at(90)) is None                                    # the gap at the bottom


def test_fast_enough_for_the_board():
	''' On the Orange Pi the home screen takes about 0.12 s; here it must stay well under a second '''
	renderer = ui.Renderer()
	view = ui.sample_views()['home']
	renderer.render(view)
	start = time.perf_counter()
	renderer.render(view)
	assert time.perf_counter() - start < 1.0
