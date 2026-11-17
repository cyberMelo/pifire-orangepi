'''
*****************************************
PiFire HDMI 5" display: screen logic
*****************************************

What the 1024x600 HDMI display shows and what touch and encoder do, with no
Redis and no hardware (display/hdmi_1024x600.py feeds it, display/hdmi_ui.py
draws the views it returns).

Commands go through the same API commands as the web app (process_command
'set' ...), so the rules for modes and set points stay in one place.  Starting
the grill, shutting it down and stopping a lit grill ask for a confirmation:
the display is on the grill and a touch can be accidental.
'''

import time

from display import hdmi_ui as ui

# Same limits and presets as the Modern dashboard (dash_modern.js)
LIMITS = {'C': (65, 260, 5), 'F': (150, 500, 5)}
DEFAULT_PRESETS = {
	'C': [('Affumicatura', 90), ('Low & slow', 110), ('Arrosto', 180), ('Rosolatura', 230)],
	'F': [('Affumicatura', 195), ('Low & slow', 225), ('Arrosto', 350), ('Rosolatura', 450)],
}
READY_MARGIN = {'C': 5, 'F': 10}   # a reached probe stays "PRONTO" until it cools this much (dashboard)

MODE_LABELS = {
	'Stop': 'SPENTO', 'Startup': 'ACCENSIONE', 'Reignite': 'RIACCENSIONE', 'Smoke': 'FUMO',
	'Hold': 'MANTENIMENTO', 'Shutdown': 'SPEGNIMENTO', 'Monitor': 'MONITOR', 'Prime': 'CARICAMENTO',
	'Manual': 'MANUALE', 'Recipe': 'RICETTA', 'Error': 'ERRORE',
}
LIT = ('Startup', 'Reignite', 'Smoke', 'Hold', 'Recipe')   # fire in the pot
IDLE_BACK_S = 45            # menu/setpoint/confirm go back home without input
WIFI_DISMISS_S = 120        # a touch on the emergency network screen shows the grill for this long
GRAPH_MINUTES = 90

ITEMS = {
	'startup': {'label': 'Accendi', 'icon': 'startup', 'note': 'Candeletta e pellet, poi il modo scelto'},
	'hold': {'label': 'Temperatura', 'icon': 'hold', 'note': 'Mantiene il grill al target'},
	'smoke': {'label': 'Fumo', 'icon': 'smoke', 'note': 'Fumo senza target'},
	'monitor': {'label': 'Monitor', 'icon': 'monitor', 'note': 'Solo lettura delle sonde'},
	'shutdown': {'label': 'Spegnimento', 'icon': 'shutdown', 'note': 'Brucia il pellet rimasto e si spegne'},
	'stop': {'label': 'Stop', 'icon': 'stop', 'note': 'Ferma tutto subito', 'danger': True},
}
CONFIRM = {
	'startup': {'icon': 'startup', 'title': 'Accendere il grill?', 'text': 'Parte la candeletta e la coclea carica il pellet.', 'ok': 'Accendi'},
	'shutdown': {'icon': 'shutdown', 'title': 'Spegnere il grill?', 'text': 'Il fuoco consuma il pellet rimasto, poi si ferma tutto.', 'ok': 'Spegni'},
	'stop': {'icon': 'stop', 'title': 'Fermare subito?', 'text': 'Nel braciere c\'è ancora fuoco: ventola e coclea si fermano di colpo.', 'ok': 'Stop', 'danger': True},
}


def menu_keys(mode):
	''' Menu entries that make sense in the current mode '''
	if mode in ('Smoke', 'Hold'):
		return ['hold', 'smoke', 'shutdown', 'stop']
	if mode in ('Startup', 'Reignite'):
		return ['shutdown', 'stop']
	if mode in ('Shutdown', 'Prime', 'Manual', 'Error', 'Recipe'):
		return ['stop']
	if mode == 'Monitor':
		return ['startup', 'stop']
	return ['startup', 'monitor']   # Stop


def mode_command(key, value=None):
	if key == 'hold':
		return ('set', ['mode', 'hold', _num(value), None])
	return ('set', ['mode', key, None, None])


def _num(value):
	return f'{value:g}'


def parse_presets(text, units):
	''' "Label:value, ..." as the Modern dashboard config (empty -> defaults) '''
	presets = []
	for item in str(text or '').split(','):
		parts = item.split(':')
		try:
			value = float(parts[-1])
		except ValueError:
			continue
		label = ':'.join(parts[:-1]).strip() or f'{value:g}°'
		presets.append((label, int(value) if value == int(value) else value))
	return presets[:4] or DEFAULT_PRESETS[units]


def fmt_temp(value, suffix=''):
	if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
		return '—'    # no reading (unplugged probe): "--" looks like two bars at 150 pt
	return f'{value:.0f}{suffix}'


def fmt_duration(seconds):
	seconds = max(0, int(seconds))
	h, rest = divmod(seconds, 3600)
	m, s = divmod(rest, 60)
	return f'{h}:{m:02d}' if h else f'{m}:{s:02d}'


class Ui:
	def __init__(self, units='C', presets=None):
		self.units = units if units in LIMITS else 'C'
		self.presets = presets or DEFAULT_PRESETS[self.units]
		self.screen = 'home'
		self.selected = 0
		self.value = None
		self.pending = None          # action waiting for confirmation
		self.confirm_choice = 'cancel'
		self.last_input = 0.0
		self.wifi_dismissed_until = 0.0
		self.message = None
		self.message_until = 0.0
		self.reached = set()         # food probes that reached their target

	# ------------------------------------------------------------ data helpers

	@staticmethod
	def _mode(data):
		return (data.get('status') or {}).get('mode', 'Stop')

	def _primary(self, data):
		probes = data.get('probes') or {}
		label = (probes.get('primary') or {}).get('label')
		temps = (data.get('current') or {}).get('P') or {}
		if label not in temps and temps:
			label = next(iter(temps))
		name = (probes.get('primary') or {}).get('name') or label or 'Grill'
		return label, name, temps.get(label)

	def _target(self, data):
		psp = (data.get('current') or {}).get('PSP')
		return psp if isinstance(psp, (int, float)) and psp > 0 else None

	def _clamp(self, value):
		vmin, vmax, step = LIMITS[self.units]
		value = round(value / step) * step
		return max(vmin, min(vmax, value))

	def _wifi_ap(self, data):
		wifi = data.get('wifi') or {}
		return wifi.get('state') == 'ap'

	# ------------------------------------------------------------ screens

	def _go(self, screen, now):
		self.screen = screen
		self.selected = 0
		self.last_input = now

	def _open_setpoint(self, data, now):
		target = self._target(data)
		if target is None:
			target = self.presets[min(1, len(self.presets) - 1)][1]
		self.value = self._clamp(target)
		self._go('setpoint', now)

	def show_message(self, text, now, seconds=8):
		self.message = text
		self.message_until = now + seconds

	def _current_screen(self, data, now):
		if self.message and now < self.message_until:
			return 'message'
		self.message = None
		if self.screen != 'home' and now - self.last_input > IDLE_BACK_S:
			self.screen = 'home'
			self.pending = None
		if self.screen == 'setpoint' and self._mode(data) not in ('Smoke', 'Hold'):
			self.screen = 'home'     # the grill moved on (shutdown, error...): no stale target editing
		if self.screen == 'home' and self._wifi_ap(data) and self._mode(data) == 'Stop' and now >= self.wifi_dismissed_until:
			return 'wifi'
		return self.screen

	# ------------------------------------------------------------ views

	def view(self, data, now=None):
		now = time.time() if now is None else now
		screen = self._current_screen(data, now)
		if screen == 'message':
			note = 'Controlla la web app per i dettagli.' if self.message == 'ERRORE' else ''
			return {'screen': 'message', 'text': self.message, 'note': note}
		if screen == 'wifi':
			ap = (data.get('wifi') or {}).get('ap') or {}
			return {'screen': 'wifi', 'ssid': ap.get('ssid', 'PiFire-Setup'), 'url': ap.get('url', 'http://10.42.0.1'),
					'qr': ap.get('qr') or f"WIFI:T:nopass;S:{ap.get('ssid', 'PiFire-Setup')};;"}
		if screen == 'setpoint':
			vmin, vmax, _ = LIMITS[self.units]
			return {'screen': 'setpoint', 'title': 'Temperatura grill', 'value': self.value, 'vmin': vmin, 'vmax': vmax,
					'units': self.units, 'presets': self.presets, 'confirm_label': 'Imposta',
					'hint': 'Ruota la manopola o tocca un preset · Premi per confermare'}
		mode = self._mode(data)
		if screen == 'menu':
			keys = menu_keys(mode)
			self.selected = min(self.selected, len(keys) - 1)
			title = MODE_LABELS.get(mode, mode).capitalize()
			if mode == 'Hold' and self._target(data):
				title += f' a {self._target(data):.0f}°'
			return {'screen': 'menu', 'title': title, 'selected': self.selected,
					'hint': 'Ruota la manopola per scegliere · Premi per confermare',
					'items': [dict(ITEMS[k], key=k) for k in keys]}
		if screen == 'confirm':
			return dict(CONFIRM[self.pending], screen='confirm', header=MODE_LABELS.get(mode, mode),
						header_active=mode in LIT, cancel='Annulla', selected=self.confirm_choice)
		return self._home(data, now)

	def _home(self, data, now):
		status = data.get('status') or {}
		mode = status.get('mode', 'Stop')
		label, name, temp = self._primary(data)
		target = self._target(data)
		started = status.get('startup_timestamp') or 0
		wifi = data.get('wifi') or {}
		wifi_state = 'ap' if wifi.get('state') == 'ap' else ('ok' if wifi.get('ip') else 'off')
		progress = None
		if target and isinstance(temp, (int, float)) and temp > 0:
			progress = max(0.0, min(1.0, temp / target))
		return {
			'screen': 'home', 'units': self.units,
			'mode_label': MODE_LABELS.get(mode, mode.upper()), 'mode_active': mode in LIT,
			'elapsed': fmt_duration(now - started) if started and mode in LIT + ('Shutdown',) else '',
			'clock': time.strftime('%H:%M', time.localtime(now)),
			'outputs': {k: bool((status.get('outpins') or {}).get(k)) for k in ('fan', 'auger', 'igniter')},
			'wifi': wifi_state,
			'grill': {'label': name, 'temp': fmt_temp(temp), 'progress': progress},
			'target': fmt_temp(target, '°') if target else None,
			'splus': bool(status.get('s_plus')) and mode in ('Smoke', 'Hold'),
			'graph': self._graph(data, label, target, now),
			'cards': self._cards(data, now),
		}

	def _food_targets(self, data):
		targets = {}
		for item in data.get('notify') or []:
			if item.get('type') == 'probe' and item.get('req') and item.get('target'):
				targets[item.get('label')] = item['target']
		return targets

	def _cards(self, data, now):
		probes = (data.get('probes') or {}).get('food') or []
		temps = (data.get('current') or {}).get('F') or {}
		targets = self._food_targets(data)
		timer = data.get('timer') or {}
		cards = []
		slots = 2 if timer.get('state', 'idle') != 'idle' else 3
		for i, probe in enumerate(probes[:slots]):
			label = probe.get('label')
			temp = temps.get(label)
			target = targets.get(label)
			card = {'type': 'probe', 'name': probe.get('name') or label, 'temp': fmt_temp(temp, '°'),
					'target': fmt_temp(target, '°') if target else None, 'progress': 0.0, 'reached': False,
					'color': ui.PROBE_COLORS[i % len(ui.PROBE_COLORS)]}
			if target and isinstance(temp, (int, float)) and temp > 0:
				card['progress'] = max(0.0, min(1.0, temp / target))
				if temp >= target:
					self.reached.add(label)
				elif temp < target - READY_MARGIN[self.units]:
					self.reached.discard(label)
				card['reached'] = label in self.reached
			else:
				self.reached.discard(label)
			cards.append(card)
		if timer.get('state', 'idle') != 'idle':
			note = 'Spegne il grill alla fine' if timer.get('shutdown') else ('In pausa' if timer['state'] == 'paused' else '')
			if timer['state'] == 'done':
				note = 'Tempo scaduto'
			cards.append({'type': 'timer', 'time': fmt_duration(timer.get('remaining', 0)), 'note': note,
						  'done': timer['state'] == 'done'})
		return cards

	def _graph(self, data, primary_label, target, now):
		history = data.get('history') or {}
		start = now - GRAPH_MINUTES * 60
		times = history.get('T') or []
		probes = (data.get('probes') or {}).get('food') or []
		_, name, _ = self._primary(data)
		wanted = [('P', primary_label, name, ui.EMBER, 2.6)]
		for i, probe in enumerate(probes[:3]):
			wanted.append(('F', probe.get('label'), probe.get('name') or probe.get('label'),
						   ui.PROBE_COLORS[i % len(ui.PROBE_COLORS)], 2))
		series, peak = [], target or 0
		for group, label, shown, color, width in wanted:
			values = (history.get(group) or {}).get(label) or []
			points = []
			for t, v in zip(times, values):
				frac = ((t or 0) / 1000 - start) / (GRAPH_MINUTES * 60)
				if 0 <= frac <= 1.0001:
					points.append((min(frac, 1.0), v))
					if isinstance(v, (int, float)):
						peak = max(peak, v)
			series.append({'name': shown, 'color': color, 'width': width, 'points': points})
		step = 50 if self.units == 'C' else 100
		vmax = max(step * 3, -(-peak * 1.1 // step) * step)
		return {'title': f'ULTIMI {GRAPH_MINUTES} MINUTI', 'series': series, 'setpoint': target, 'vmax': vmax,
				'xlabels': [(0, f'-{GRAPH_MINUTES}′'), (1 / 3, f'-{GRAPH_MINUTES * 2 // 3}′'),
							(2 / 3, f'-{GRAPH_MINUTES // 3}′'), (1, 'ora')]}

	# ------------------------------------------------------------ input

	def touch(self, x, y, data, now=None):
		''' A tap at pixel (x, y): returns the commands to send '''
		now = time.time() if now is None else now
		view = self.view(data, now)
		self.last_input = now
		target = ui.hit(view, x, y)
		screen = view['screen']
		if screen == 'message':
			self.message = None
			return []
		if screen == 'wifi':
			self.wifi_dismissed_until = now + WIFI_DISMISS_S
			return []
		if target is None:
			return []
		if target == 'back':
			self._go('home', now)
			return []
		if screen == 'home':
			if target == 'menu':
				self._go('menu', now)
			elif target == 'setpoint' and self._mode(data) in ('Smoke', 'Hold'):
				self._open_setpoint(data, now)
			return []
		if screen == 'setpoint':
			if target.startswith('preset:'):
				self.value = self._clamp(self.presets[int(target.split(':')[1])][1])
			elif target == 'dial':
				value = ui.dial_value(view, x, y)
				if value is not None:
					self.value = self._clamp(value)
			elif target == 'confirm':
				return self._confirm_setpoint(data, now)
			return []
		if screen == 'menu':
			self.selected = int(target.split(':')[1])
			return self._activate(view['items'][self.selected]['key'], data, now)
		if screen == 'confirm':
			return self._answer(target == 'ok', now)
		return []

	def rotate(self, steps, data, now=None):
		''' Encoder turned by steps (positive = clockwise) '''
		now = time.time() if now is None else now
		view = self.view(data, now)
		self.last_input = now
		screen = view['screen']
		if screen == 'wifi':
			self.wifi_dismissed_until = now + WIFI_DISMISS_S
		elif screen == 'home':
			if self._mode(data) in ('Smoke', 'Hold'):
				self._open_setpoint(data, now)
				self.value = self._clamp(self.value + steps * LIMITS[self.units][2])
		elif screen == 'setpoint':
			self.value = self._clamp(self.value + steps * LIMITS[self.units][2])
		elif screen == 'menu':
			self.selected = (self.selected + steps) % len(view['items'])
		elif screen == 'confirm':
			self.confirm_choice = 'ok' if self.confirm_choice == 'cancel' else 'cancel'
		return []

	def press(self, data, now=None):
		''' Encoder button pressed '''
		now = time.time() if now is None else now
		view = self.view(data, now)
		self.last_input = now
		screen = view['screen']
		if screen == 'message':
			self.message = None
		elif screen == 'wifi':
			self.wifi_dismissed_until = now + WIFI_DISMISS_S
		elif screen == 'home':
			self._go('menu', now)
		elif screen == 'setpoint':
			return self._confirm_setpoint(data, now)
		elif screen == 'menu':
			return self._activate(view['items'][self.selected]['key'], data, now)
		elif screen == 'confirm':
			return self._answer(self.confirm_choice == 'ok', now)
		return []

	def _activate(self, key, data, now):
		mode = self._mode(data)
		if key == 'hold':
			self._open_setpoint(data, now)
			return []
		if key in ('startup', 'shutdown') or (key == 'stop' and mode in LIT + ('Shutdown',)):
			self.pending = key
			self.confirm_choice = 'cancel'   # the safe answer is the default
			self._go('confirm', now)
			return []
		self._go('home', now)
		return [mode_command(key)]

	def _answer(self, ok, now):
		key, self.pending = self.pending, None
		self._go('home', now)
		return [mode_command(key)] if ok and key else []

	def _confirm_setpoint(self, data, now):
		mode = self._mode(data)
		self._go('home', now)
		if mode == 'Hold':
			return [('set', ['psp', _num(self.value), None, None])]
		if mode == 'Smoke':
			return [mode_command('hold', self.value)]
		return []     # not lit: the target applies when the grill is running (web app does the same)
