'''
*****************************************
PiFire HDMI 5" display: screens
*****************************************

Draws the screens of the 1024x600 HDMI display (MPI5006, Orange Pi fork) with
Pillow, from a "view" prepared by display/hdmi_state.py.  Pure drawing: no
Redis, no hardware.  The touch areas of each screen are defined here too
(targets()), next to the drawing they belong to.

Design units: 1 unit = 1.25 px, so the texts have the physical size of the
first 800x480 drafts on the 108 mm wide glass; the screen is W = 819.2 units
wide and 480 high.  Fonts: Barlow (SIL Open Font License, display/fonts) and
the FontAwesome icons PiFire already ships.

Previews of every screen (docs-orangepi/display-mockups):
	python -m display.hdmi_ui docs-orangepi/display-mockups
'''

import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')
FA = os.path.join(HERE, '..', 'static', 'font', 'FA-Free-Solid.otf')

PX_W, PX_H = 1024, 600
DS = 1.25                        # pixels per design unit
W, H = PX_W / DS, PX_H / DS      # 819.2 x 480 units

BG = (12, 14, 15); CARD = (24, 27, 29); LINE = (44, 48, 51); GRID = (32, 36, 38)
TEXT = (244, 241, 236); MUTED = (135, 141, 146); EMBER = (255, 110, 30); OK = (88, 200, 120)
DANGER = (235, 80, 70)
PROBE_COLORS = [(120, 190, 255), (200, 160, 255), (250, 205, 90)]
SETPOINT_DASH = (150, 70, 25)

# FontAwesome code points
ICON = {
	'fan': 0xf863, 'auger': 0xf101, 'igniter': 0xf46a, 'wifi': 0xf1eb, 'clock': 0xf017,
	'smoke': 0xf0c2, 'target': 0xf140, 'timer': 0xf2f2, 'back': 0xf060,
	'startup': 0xf04b, 'hold': 0xf2c9, 'shutdown': 0xf011, 'stop': 0xf04d, 'monitor': 0xf06e,
	'warning': 0xf071,
}

STATUS_H = 58                   # status bar height (units)
CARD_GAP = 19
CARD_W = (W - 48 - 2 * CARD_GAP) / 3
CARD_Y0, CARD_Y1 = 318, 456
GRAPH_BOX = (352, 72, W - 24, 300)
PRESET_X0, PRESET_X1 = W - 24 - 170, W - 24
PRESET_Y0, PRESET_STEP, PRESET_H = 144, 58, 46
CONFIRM_BOX = (PRESET_X0, 400, PRESET_X1, 446)
DIAL = ((W - 200) / 2, 262, 150)  # centre x, centre y, radius
MENU_X0, MENU_COLS, MENU_ROW_H, MENU_GAP = 24, 2, 96, 16


class Fonts:
	''' Barlow and FontAwesome at a given oversampling factor, cached per size '''

	def __init__(self, scale):
		self.scale = scale
		self._cache = {}

	def _get(self, path, px):
		key = (path, px)
		if key not in self._cache:
			self._cache[key] = ImageFont.truetype(path, max(1, int(px * self.scale)))
		return self._cache[key]

	def big(self, px): return self._get(os.path.join(FONTS, 'BarlowCondensed-SemiBold.ttf'), px)
	def med(self, px): return self._get(os.path.join(FONTS, 'BarlowCondensed-Medium.ttf'), px)
	def ui(self, px): return self._get(os.path.join(FONTS, 'Barlow-SemiBold.ttf'), px)
	def uir(self, px): return self._get(os.path.join(FONTS, 'Barlow-Medium.ttf'), px)
	def icon(self, px): return self._get(FA, px)


class Canvas:
	''' Drawing in design units; oversampling SS > 1 only for the previews '''

	def __init__(self, fonts, ss=1):
		self.ss = ss
		self.k = DS * ss
		self.f = fonts
		self.im = Image.new('RGB', (PX_W * ss, PX_H * ss), BG)
		self.d = ImageDraw.Draw(self.im)

	def s(self, *v): return [x * self.k for x in v]

	def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=1):
		if x1 <= x0 or y1 <= y0:
			return
		self.d.rounded_rectangle(self.s(x0, y0, x1, y1), radius=r * self.k, fill=fill, outline=outline,
								 width=max(1, int(width * self.k)))

	def text(self, x, y, t, font, fill, anchor='la'):
		self.d.text((x * self.k, y * self.k), t, font=font, fill=fill, anchor=anchor)

	def tw(self, t, font): return self.d.textlength(t, font=font) / self.k

	def line(self, pts, fill, width=1):
		if len(pts) > 1:
			self.d.line([(x * self.k, y * self.k) for x, y in pts], fill=fill, width=max(1, int(width * self.k)), joint='curve')

	def circle(self, cx, cy, r, fill=None, outline=None, width=1):
		self.d.ellipse(self.s(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=max(1, int(width * self.k)))

	def icon(self, x, y, name, px, fill, anchor='mm'):
		self.text(x, y, chr(ICON[name]), self.f.icon(px), fill, anchor)

	def paste(self, img, x, y, side):
		img = img.resize((int(side * self.k), int(side * self.k)), Image.NEAREST)
		self.im.paste(img, (int(x * self.k), int(y * self.k)))

	def done(self):
		if self.ss == 1:
			return self.im
		return self.im.resize((PX_W, PX_H), Image.LANCZOS)


def px(box):
	''' Design-unit box -> pixel box (for the touch areas) '''
	return tuple(int(round(v * DS)) for v in box)


'''
==============================
  Touch areas
==============================
'''

def card_x(i):
	return 24 + i * (CARD_W + CARD_GAP)


def menu_box(i):
	col, row = i % MENU_COLS, i // MENU_COLS
	w = (W - 2 * MENU_X0 - (MENU_COLS - 1) * MENU_GAP) / MENU_COLS
	x0 = MENU_X0 + col * (w + MENU_GAP)
	y0 = 84 + row * (MENU_ROW_H + MENU_GAP)
	return (x0, y0, x0 + w, y0 + MENU_ROW_H)


def confirm_buttons():
	w = 220
	return {'cancel': (W / 2 - w - 12, 330, W / 2 - 12, 400), 'ok': (W / 2 + 12, 330, W / 2 + 12 + w, 400)}


def targets(view):
	''' [(name, pixel box)] the touch screen reacts to on this view, first match wins '''
	screen = view['screen']
	back = ('back', px((0, 0, 260, STATUS_H)))
	if screen == 'home':
		return [('menu', px((0, 0, W / 2 - 40, STATUS_H))),
				('setpoint', px((0, STATUS_H + 2, 340, 310)))]
	if screen == 'setpoint':
		areas = [back, ('confirm', px(CONFIRM_BOX))]
		for i, _ in enumerate(view['presets']):
			y = PRESET_Y0 + i * PRESET_STEP
			areas.append((f'preset:{i}', px((PRESET_X0, y, PRESET_X1, y + PRESET_H))))
		cx, cy, r = DIAL
		areas.append(('dial', px((cx - r - 30, cy - r - 30, cx + r + 30, cy + r + 30))))
		return areas
	if screen == 'menu':
		return [back] + [(f'item:{i}', px(menu_box(i))) for i, _ in enumerate(view['items'])]
	if screen == 'confirm':
		return [(name, px(box)) for name, box in confirm_buttons().items()]
	if screen in ('wifi', 'message'):
		return [('dismiss', (0, 0, PX_W, PX_H))]
	return []


def hit(view, x, y):
	for name, (x0, y0, x1, y1) in targets(view):
		if x0 <= x < x1 and y0 <= y < y1:
			return name
	return None


def dial_value(view, x, y):
	''' Temperature for a touch on the dial (pixels), or None in the dead zone at the bottom '''
	cx, cy, r = DIAL
	dx, dy = x / DS - cx, y / DS - cy
	angle = (math.degrees(math.atan2(dy, dx)) - 135) % 360   # 0 at the start of the arc, clockwise
	if angle > 270:
		return None
	return view['vmin'] + (view['vmax'] - view['vmin']) * angle / 270


'''
==============================
  Screens
==============================
'''

def _status_bar(c, title, dot, right=None):
	f = c.f
	c.circle(26, 30, 6, EMBER if dot else LINE)
	c.text(42, 30, title, f.ui(20), TEXT, 'lm')
	if right:
		right(c)
	c.line([(0, STATUS_H), (W, STATUS_H)], LINE, 1)


def _home_status(c, v):
	f = c.f

	def right(c):
		x = W - 24
		wifi_col = {'ok': TEXT, 'ap': EMBER}.get(v['wifi'], LINE)
		c.icon(x, 30, 'wifi', 18, wifi_col, 'rm'); x -= 40
		for name in ('igniter', 'auger', 'fan'):
			c.icon(x, 30, name, 18, EMBER if v['outputs'].get(name) else LINE, 'rm'); x -= 40
		c.text(x - 6, 30, v['clock'], f.med(22), MUTED, 'rm')
		if v['elapsed']:
			c.icon(W / 2 - 14, 30, 'clock', 17, MUTED, 'mm')
			c.text(W / 2, 30, v['elapsed'], f.med(26), TEXT, 'lm')

	_status_bar(c, v['mode_label'], v['mode_active'], right)


def _grill_block(c, v):
	f = c.f
	g = v['grill']
	c.text(28, 76, g['label'].upper(), f.ui(17), MUTED, 'la')
	big = f.big(150)
	c.text(20, 236, g['temp'], big, TEXT, 'ls')
	c.text(28 + c.tw(g['temp'], big), 108, '°' + v['units'], f.med(32), MUTED, 'la')
	c.rrect(28, 252, 330, 258, 3, fill=LINE)
	if g['progress'] is not None:
		c.rrect(28, 252, 28 + 302 * g['progress'], 258, 3, fill=EMBER)
	c.rrect(28, 272, 176, 300, 14, fill=CARD)
	c.text(44, 286, 'TARGET', f.ui(13), MUTED, 'lm')
	c.text(160, 286, v['target'] or '—', f.big(26), EMBER if v['target'] else MUTED, 'rm')
	if v['splus']:
		c.rrect(186, 272, 330, 300, 14, outline=LINE, width=1.5)
		c.icon(204, 286, 'smoke', 14, TEXT, 'lm')
		c.text(228, 286, 'Smoke+ attivo', f.uir(15), TEXT, 'lm')


def _graph(c, v):
	f = c.f
	gr = v['graph']
	x0, y0, x1, y1 = GRAPH_BOX
	c.rrect(x0, y0, x1, y1, 16, fill=CARD)
	c.text(x0 + 18, y0 + 20, gr['title'], f.ui(13), MUTED, 'lm')
	lx = x1 - 18
	for s in reversed(gr['series']):
		c.text(lx, y0 + 20, s['name'], f.uir(13), TEXT, 'rm'); lx -= c.tw(s['name'], f.uir(13)) + 8
		c.circle(lx, y0 + 20, 4, s['color']); lx -= 18
	gx0, gy0, gx1, gy1 = x0 + 44, y0 + 44, x1 - 18, y1 - 30
	vmax = gr['vmax']
	ty = lambda val: gy1 - (min(val, vmax) / vmax) * (gy1 - gy0)
	tx = lambda frac: gx0 + frac * (gx1 - gx0)
	for i in range(4):
		val = vmax * i / 3
		c.line([(gx0, ty(val)), (gx1, ty(val))], GRID, 1)
		c.text(gx0 - 8, ty(val), f'{val:.0f}°', f.med(13), MUTED, 'rm')
	for frac, label in gr['xlabels']:
		c.text(tx(frac), gy1 + 16, label, f.med(13), MUTED, 'mm')
	if gr['setpoint']:
		sx = gx0
		while sx < gx1:
			c.line([(sx, ty(gr['setpoint'])), (min(sx + 6, gx1), ty(gr['setpoint']))], SETPOINT_DASH, 1)
			sx += 12
	for s in reversed(gr['series']):
		segment = []
		for frac, val in s['points']:
			if val is None:
				c.line(segment, s['color'], s['width']); segment = []
			else:
				segment.append((tx(frac), ty(val)))
		c.line(segment, s['color'], s['width'])
	if gr['series'] and gr['series'][0]['points'] and gr['series'][0]['points'][-1][1] is not None:
		frac, val = gr['series'][0]['points'][-1]
		c.circle(tx(frac), ty(val), 5, gr['series'][0]['color'])
	if not any(s['points'] for s in gr['series']):
		c.text((gx0 + gx1) / 2, (gy0 + gy1) / 2, 'Nessun dato ancora', f.uir(15), MUTED, 'mm')


def _probe_card(c, x0, card):
	f = c.f
	x1, y0, y1 = x0 + CARD_W, CARD_Y0, CARD_Y1
	c.rrect(x0, y0, x1, y1, 16, fill=CARD)
	c.circle(x0 + 24, y0 + 26, 5, card['color'])
	c.text(x0 + 36, y0 + 26, card['name'].upper(), f.ui(15), MUTED, 'lm')
	reached = card['reached']
	c.text(x0 + 20, y0 + 102, card['temp'], f.big(72), OK if reached else TEXT, 'ls')
	if card['target']:
		c.text(x1 - 20, y0 + 96, card['target'], f.med(26), MUTED, 'rs')
		c.icon(x1 - 26 - c.tw(card['target'], f.med(26)), y0 + 86, 'target', 14, MUTED, 'rm')
		c.rrect(x0 + 20, y1 - 22, x1 - 20, y1 - 16, 3, fill=LINE)
		c.rrect(x0 + 20, y1 - 22, x0 + 20 + (x1 - x0 - 40) * card['progress'], y1 - 16, 3, fill=OK if reached else EMBER)
	if reached:
		c.text(x1 - 20, y0 + 26, 'PRONTO', f.ui(13), OK, 'rm')


def _timer_card(c, x0, card):
	f = c.f
	x1, y0, y1 = x0 + CARD_W, CARD_Y0, CARD_Y1
	c.rrect(x0, y0, x1, y1, 16, fill=CARD)
	c.icon(x0 + 20, y0 + 26, 'timer', 15, MUTED, 'lm')
	c.text(x0 + 42, y0 + 26, 'TIMER', f.ui(15), MUTED, 'lm')
	c.text(x0 + 20, y0 + 102, card['time'], f.big(72), OK if card['done'] else TEXT, 'ls')
	if card['note']:
		c.text(x0 + 20, y1 - 20, card['note'], f.uir(15), MUTED, 'lm')


def screen_home(c, v):
	_home_status(c, v)
	_grill_block(c, v)
	_graph(c, v)
	for i, card in enumerate(v['cards'][:3]):
		if card['type'] == 'timer':
			_timer_card(c, card_x(i), card)
		else:
			_probe_card(c, card_x(i), card)


def screen_setpoint(c, v):
	f = c.f
	c.icon(28, 30, 'back', 18, MUTED, 'lm')
	c.text(58, 30, v['title'], f.ui(20), TEXT, 'lm')
	c.line([(0, STATUS_H), (W, STATUS_H)], LINE, 1)
	cx, cy, r = DIAL
	a0 = 135
	box = c.s(cx - r, cy - r, cx + r, cy + r)
	c.d.arc(box, a0, a0 + 270, fill=LINE, width=int(18 * c.k))
	frac = max(0.0, min(1.0, (v['value'] - v['vmin']) / (v['vmax'] - v['vmin'])))
	if frac > 0:
		c.d.arc(box, a0, a0 + 270 * frac, fill=EMBER, width=int(18 * c.k))
	ang = math.radians(a0 + 270 * frac)
	c.circle(cx + r * math.cos(ang), cy + r * math.sin(ang), 15, TEXT)
	c.text(cx, cy + 30, f"{v['value']:g}", f.big(150), TEXT, 'ms')
	c.text(cx, cy + 64, '°' + v['units'], f.med(32), MUTED, 'mm')
	c.text(cx - r + 4, cy + r - 26, f"{v['vmin']:g}°", f.med(22), MUTED, 'mm')
	c.text(cx + r - 4, cy + r - 26, f"{v['vmax']:g}°", f.med(22), MUTED, 'mm')
	c.text(PRESET_X0 + 10, 120, 'PRESET', f.ui(13), MUTED, 'la')
	for i, (label, value) in enumerate(v['presets']):
		y = PRESET_Y0 + i * PRESET_STEP
		on = value == v['value']
		c.rrect(PRESET_X0, y, PRESET_X1, y + PRESET_H, 12, fill=CARD if on else None, outline=None if on else LINE, width=1.5)
		c.text(PRESET_X0 + 16, y + 23, label, f.ui(15) if on else f.uir(15), TEXT if on else MUTED, 'lm')
		c.text(PRESET_X1 - 14, y + 23, f'{value:g}°', f.med(20), EMBER if on else MUTED, 'rm')
	x0, y0, x1, y1 = CONFIRM_BOX
	c.rrect(x0, y0, x1, y1, 12, fill=EMBER)
	c.text((x0 + x1) / 2, (y0 + y1) / 2, v['confirm_label'], f.ui(17), BG, 'mm')
	c.text(W / 2 - 100, 462, v['hint'], f.uir(15), MUTED, 'mm')


def screen_menu(c, v):
	f = c.f
	c.icon(28, 30, 'back', 18, MUTED, 'lm')
	c.text(58, 30, v['title'], f.ui(20), TEXT, 'lm')
	c.line([(0, STATUS_H), (W, STATUS_H)], LINE, 1)
	for i, item in enumerate(v['items']):
		x0, y0, x1, y1 = menu_box(i)
		selected = i == v['selected']
		c.rrect(x0, y0, x1, y1, 16, fill=CARD, outline=EMBER if selected else None, width=2)
		col = DANGER if item.get('danger') else EMBER
		c.circle(x0 + 48, (y0 + y1) / 2, 26, fill=(40, 30, 26) if not item.get('danger') else (48, 28, 28))
		c.icon(x0 + 48, (y0 + y1) / 2, item['icon'], 20, col, 'mm')
		c.text(x0 + 92, (y0 + y1) / 2 - 12, item['label'], f.big(30), TEXT, 'lm')
		c.text(x0 + 92, (y0 + y1) / 2 + 20, item['note'], f.uir(14), MUTED, 'lm')
	if v.get('hint'):
		c.text(W / 2, 462, v['hint'], f.uir(15), MUTED, 'mm')


def screen_confirm(c, v):
	f = c.f
	_status_bar(c, v['header'], v.get('header_active', False))
	c.icon(W / 2, 150, v['icon'], 44, DANGER if v.get('danger') else EMBER, 'mm')
	c.text(W / 2, 222, v['title'], f.big(44), TEXT, 'mm')
	c.text(W / 2, 268, v['text'], f.uir(17), MUTED, 'mm')
	for name, (x0, y0, x1, y1) in confirm_buttons().items():
		selected = (name == 'ok') == (v['selected'] == 'ok')
		if name == 'ok':
			c.rrect(x0, y0, x1, y1, 16, fill=DANGER if v.get('danger') else EMBER, outline=TEXT if selected else None, width=2)
			c.text((x0 + x1) / 2, (y0 + y1) / 2, v['ok'], f.ui(20), BG, 'mm')
		else:
			c.rrect(x0, y0, x1, y1, 16, fill=CARD, outline=TEXT if selected else LINE, width=2 if selected else 1.5)
			c.text((x0 + x1) / 2, (y0 + y1) / 2, v['cancel'], f.ui(20), TEXT, 'mm')
	c.text(W / 2, 452, 'Ruota la manopola per scegliere · Premi per confermare', f.uir(15), MUTED, 'mm')


def screen_wifi(c, v):
	import qrcode
	f = c.f
	_status_bar(c, 'RETE DI EMERGENZA', True, lambda c: c.icon(W - 24, 30, 'wifi', 18, EMBER, 'rm'))
	c.text(28, 92, 'Il grill non trova il Wi-Fi', f.big(40), TEXT, 'lm')
	c.text(28, 128, 'Scegli la rete nuova dal telefono, in due passi:', f.uir(17), MUTED, 'lm')
	steps = (('1', 'Collegati alla rete', v['ssid'], 'senza password'),
			 ('2', 'Apri nel browser', v['url'], 'si apre anche da sola'))
	for i, (n, label, big, note) in enumerate(steps):
		y0 = 156 + i * 118; x1 = W - 24 - 262
		c.rrect(24, y0, x1, y0 + 102, 16, fill=CARD)
		c.circle(62, y0 + 51, 22, EMBER); c.text(62, y0 + 51, n, f.big(30), (26, 14, 6), 'mm')
		c.text(100, y0 + 30, label.upper(), f.ui(14), MUTED, 'lm')
		c.text(100, y0 + 66, big, f.big(38), TEXT, 'lm')
		c.text(x1 - 18, y0 + 30, note, f.uir(14), MUTED, 'rm')
	c.text(28, 416, 'Da questa rete si sceglie solo il Wi-Fi: il grill non si comanda.', f.uir(15), MUTED, 'lm')
	c.text(28, 444, 'Tocca lo schermo per tornare al grill.', f.uir(15), MUTED, 'lm')
	qx0, qy0, qx1 = W - 24 - 244, 156, W - 24
	c.rrect(qx0, qy0, qx1, qy0 + 220, 16, fill=CARD)
	qr = qrcode.QRCode(border=2, box_size=10)
	qr.add_data(v['qr'])
	qr.make(fit=True)
	img = qr.make_image(fill_color=BG, back_color=TEXT).convert('RGB')
	c.paste(img, qx0 + (qx1 - qx0 - 168) / 2, qy0 + 16, 168)
	c.text((qx0 + qx1) / 2, qy0 + 204, 'Inquadra per collegarti', f.uir(14), MUTED, 'mm')


def screen_message(c, v):
	f = c.f
	c.icon(W / 2, 170, 'warning', 54, DANGER, 'mm')
	c.text(W / 2, 260, v['text'], f.big(56), TEXT, 'mm')
	if v.get('note'):
		c.text(W / 2, 312, v['note'], f.uir(17), MUTED, 'mm')


SCREENS = {'home': screen_home, 'setpoint': screen_setpoint, 'menu': screen_menu,
		   'confirm': screen_confirm, 'wifi': screen_wifi, 'message': screen_message}


class Renderer:
	def __init__(self, ss=1):
		self.ss = ss
		self.fonts = Fonts(DS * ss)

	def render(self, view):
		c = Canvas(self.fonts, self.ss)
		SCREENS[view['screen']](c, view)
		return c.done()


'''
==============================
  Previews
==============================
'''

def sample_views():
	''' The screens of the drafts with plausible data (previews and tests) '''
	import random
	random.seed(7)
	n = 90
	grill, p1, p2 = [], [], []
	for m in range(n):
		grill.append(22 + 88 * (1 - math.exp(-m / 9)) + (random.uniform(-2.5, 2.5) if m > 20 else 0))
		p1.append(8 + 63 * (1 - math.exp(-m / 70)) / (1 - math.exp(-(n - 1) / 70)))
		p2.append(8 + 66 * (1 - math.exp(-m / 38)) / (1 - math.exp(-(n - 1) / 38)))
	grill[-1] = 112
	pts = lambda values: [(i / (n - 1), v) for i, v in enumerate(values)]
	presets = [('Affumicatura', 90), ('Low & slow', 110), ('Arrosto', 180), ('Rosolatura', 230)]
	home = {
		'screen': 'home', 'units': 'C', 'mode_label': 'MANTENIMENTO', 'mode_active': True,
		'elapsed': '2:14', 'clock': '18:47', 'outputs': {'fan': True, 'auger': True, 'igniter': False}, 'wifi': 'ok',
		'grill': {'label': 'Grill', 'temp': '112', 'progress': 1.0}, 'target': '110°', 'splus': True,
		'graph': {'title': 'ULTIMI 90 MINUTI', 'vmax': 150, 'setpoint': 110,
				  'xlabels': [(0, '-90′'), (1 / 3, '-60′'), (2 / 3, '-30′'), (1, 'ora')],
				  'series': [{'name': 'Grill', 'color': EMBER, 'width': 2.6, 'points': pts(grill)},
							 {'name': 'Spalla', 'color': PROBE_COLORS[0], 'width': 2, 'points': pts(p1)},
							 {'name': 'Petto', 'color': PROBE_COLORS[1], 'width': 2, 'points': pts(p2)}]},
		'cards': [{'type': 'probe', 'name': 'Spalla', 'temp': '71°', 'target': '93°', 'progress': 71 / 93, 'reached': False, 'color': PROBE_COLORS[0]},
				  {'type': 'probe', 'name': 'Petto', 'temp': '74°', 'target': '74°', 'progress': 1.0, 'reached': True, 'color': PROBE_COLORS[1]},
				  {'type': 'timer', 'time': '45:00', 'note': 'Spegne il grill alla fine', 'done': False}],
	}
	return {
		'home': home,
		'setpoint': {'screen': 'setpoint', 'title': 'Temperatura grill', 'value': 110, 'vmin': 65, 'vmax': 260, 'units': 'C',
					 'presets': presets, 'confirm_label': 'Imposta', 'hint': 'Ruota la manopola o tocca un preset · Premi per confermare'},
		'menu': {'screen': 'menu', 'title': 'Mantenimento a 110°', 'selected': 0, 'hint': 'Ruota la manopola per scegliere · Premi per confermare',
				 'items': [{'key': 'hold', 'label': 'Temperatura', 'icon': 'hold', 'note': 'Cambia il target del grill'},
						   {'key': 'smoke', 'label': 'Fumo', 'icon': 'smoke', 'note': 'Fumo senza target'},
						   {'key': 'shutdown', 'label': 'Spegnimento', 'icon': 'shutdown', 'note': 'Brucia il pellet rimasto e si spegne'},
						   {'key': 'stop', 'label': 'Stop', 'icon': 'stop', 'note': 'Ferma tutto subito', 'danger': True}]},
		'confirm': {'screen': 'confirm', 'header': 'SPENTO', 'icon': 'startup', 'title': 'Accendere il grill?',
					'text': 'Parte la candeletta e la coclea carica il pellet.', 'ok': 'Accendi', 'cancel': 'Annulla', 'selected': 'cancel'},
		'wifi': {'screen': 'wifi', 'ssid': 'PiFire-Setup', 'url': 'http://10.42.0.1', 'qr': 'WIFI:T:nopass;S:PiFire-Setup;;'},
		'message': {'screen': 'message', 'text': 'ERRORE', 'note': 'Controlla la web app per i dettagli.'},
	}


if __name__ == '__main__':
	import sys
	out = sys.argv[1] if len(sys.argv) > 1 else '.'
	renderer = Renderer(ss=3)
	for name, view in sample_views().items():
		renderer.render(view).save(os.path.join(out, f'5in_{name}.png'))
	print('ok')
