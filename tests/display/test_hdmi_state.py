'''
HDMI 5" display (display/hdmi_state.py): what the screens show from the Redis
data and which API commands touch and encoder send.  Starting, shutting down
and stopping a lit grill need a confirmation whose default answer is "no".
'''

import os
import sys
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
pytest.importorskip('PIL')

from display import hdmi_state as hs   # noqa: E402
from display import hdmi_ui as ui      # noqa: E402

NOW = 1_800_000_000.0


def data(mode='Hold', grill=112, psp=110, food=None, wifi=None, timer=None, splus=False, history=None):
	food = {'Probe1': 71, 'Probe2': 74} if food is None else food
	return {
		'probes': {'primary': {'name': 'Grill', 'label': 'Grill'},
				   'food': [{'name': 'Spalla', 'label': 'Probe1'}, {'name': 'Petto', 'label': 'Probe2'}]},
		'current': {'P': {'Grill': grill}, 'F': food, 'PSP': psp, 'NT': {}, 'AUX': {}},
		'status': {'mode': mode, 's_plus': splus, 'startup_timestamp': NOW - 2 * 3600 - 14 * 60,
				   'outpins': {'fan': True, 'auger': False, 'igniter': False, 'power': True}},
		'notify': [{'type': 'probe', 'label': 'Probe1', 'req': True, 'target': 93},
				   {'type': 'probe', 'label': 'Probe2', 'req': True, 'target': 74},
				   {'type': 'probe_limit_high', 'label': 'Probe1', 'req': True, 'target': 300}],
		'timer': timer or {'state': 'idle', 'remaining': 0},
		'wifi': wifi if wifi is not None else {'state': 'client', 'ip': '192.168.10.151'},
		'history': history or {'T': [], 'P': {}, 'F': {}, 'PSP': []},
	}


def centre(view, name):
	for target, (x0, y0, x1, y1) in ui.targets(view):
		if target == name:
			return (x0 + x1) // 2, (y0 + y1) // 2
	raise AssertionError(f'no touch area {name} on {view["screen"]}')


def tap(u, d, name, now=NOW):
	return u.touch(*centre(u.view(d, now), name), d, now)


# ------------------------------------------------------------ home screen

def test_home_shows_grill_target_probes_and_outputs():
	v = hs.Ui('C').view(data(splus=True), NOW)
	assert v['screen'] == 'home'
	assert v['mode_label'] == 'MANTENIMENTO' and v['mode_active']
	assert v['elapsed'] == '2:14'
	assert v['grill'] == {'label': 'Grill', 'temp': '112', 'progress': 1.0}
	assert v['target'] == '110°' and v['splus']
	assert v['outputs'] == {'fan': True, 'auger': False, 'igniter': False}
	assert [c['name'] for c in v['cards']] == ['Spalla', 'Petto']
	assert v['cards'][0]['target'] == '93°' and not v['cards'][0]['reached']
	assert v['cards'][1]['reached']     # 74 of 74


def test_stopped_grill_has_no_target_timer_or_smoke_plus():
	v = hs.Ui('C').view(data(mode='Stop', grill=0, psp=0, splus=True), NOW)
	assert v['mode_label'] == 'SPENTO' and not v['mode_active']
	assert v['grill']['temp'] == '—' and v['target'] is None and v['grill']['progress'] is None
	assert v['elapsed'] == '' and not v['splus']


def test_timer_takes_the_third_card():
	timer = {'state': 'running', 'remaining': 45 * 60, 'shutdown': True}
	cards = hs.Ui('C').view(data(timer=timer), NOW)['cards']
	assert [c['type'] for c in cards] == ['probe', 'probe', 'timer']
	assert cards[2]['time'] == '45:00' and cards[2]['note'] == 'Spegne il grill alla fine'


def test_ready_probe_stays_ready_until_it_cools_by_the_margin():
	u = hs.Ui('C')
	assert u.view(data(food={'Probe1': 93, 'Probe2': 0}), NOW)['cards'][0]['reached']
	assert u.view(data(food={'Probe1': 89, 'Probe2': 0}), NOW)['cards'][0]['reached']       # within 5 °C
	assert not u.view(data(food={'Probe1': 87, 'Probe2': 0}), NOW)['cards'][0]['reached']


def test_graph_places_points_by_time_and_keeps_gaps():
	t = lambda minutes_ago: (NOW - minutes_ago * 60) * 1000
	history = {'T': [t(120), t(90), t(45), t(0)], 'PSP': [0, 110, 110, 110],
			   'P': {'Grill': [20, 60, None, 112]}, 'F': {'Probe1': [None, 10, 40, 71]}}
	g = hs.Ui('C').view(data(history=history), NOW)['graph']
	grill = g['series'][0]
	assert grill['name'] == 'Grill' and grill['color'] == ui.EMBER
	assert [round(f, 2) for f, _ in grill['points']] == [0.0, 0.5, 1.0]    # the point 2 hours ago is off the graph
	assert [v for _, v in grill['points']] == [60, None, 112]
	assert g['setpoint'] == 110 and g['vmax'] == 150


# ------------------------------------------------------------ set point

def test_encoder_on_home_opens_the_set_point_from_the_current_target():
	u = hs.Ui('C')
	assert u.rotate(1, data(), NOW) == []
	v = u.view(data(), NOW)
	assert v['screen'] == 'setpoint' and v['value'] == 115
	assert u.press(data(), NOW) == [('set', ['psp', '115', None, None])]
	assert u.view(data(), NOW)['screen'] == 'home'


def test_set_point_from_smoke_switches_to_hold():
	u = hs.Ui('C')
	tap(u, data(mode='Smoke', psp=0), 'setpoint')
	tap(u, data(mode='Smoke', psp=0), 'preset:2')                      # Arrosto 180
	assert tap(u, data(mode='Smoke', psp=0), 'confirm') == [('set', ['mode', 'hold', '180', None])]


def test_set_point_is_clamped_to_the_dashboard_limits():
	u = hs.Ui('C')
	u.rotate(1, data(), NOW)
	u.rotate(100, data(), NOW)
	assert u.view(data(), NOW)['value'] == 260
	u.rotate(-200, data(), NOW)
	assert u.view(data(), NOW)['value'] == 65


def test_touching_the_dial_picks_a_temperature():
	u = hs.Ui('C')
	u.rotate(1, data(), NOW)
	v = u.view(data(), NOW)
	cx, cy, r = ui.DIAL
	u.touch(int(cx * ui.DS), int((cy - r) * ui.DS), data(), NOW)        # top of the arc = middle of the range
	assert u.view(data(), NOW)['value'] == pytest.approx((v['vmin'] + v['vmax']) / 2, abs=5)


def test_no_set_point_while_the_grill_is_not_lit():
	u = hs.Ui('C')
	u.rotate(3, data(mode='Stop'), NOW)
	assert u.view(data(mode='Stop'), NOW)['screen'] == 'home'
	tap(u, data(mode='Stop'), 'setpoint')
	assert u.view(data(mode='Stop'), NOW)['screen'] == 'home'


def test_set_point_screen_closes_when_the_grill_moves_on():
	u = hs.Ui('C')
	u.rotate(1, data(), NOW)
	assert u.view(data(mode='Shutdown'), NOW)['screen'] == 'home'


# ------------------------------------------------------------ menu and confirmation

def test_menu_entries_follow_the_mode():
	assert hs.menu_keys('Stop') == ['startup', 'monitor', 'poweroff']
	assert hs.menu_keys('Hold') == ['hold', 'smoke', 'shutdown', 'stop']
	assert hs.menu_keys('Startup') == ['shutdown', 'stop']
	assert hs.menu_keys('Shutdown') == ['stop']


def test_startup_needs_a_confirmation_that_defaults_to_no():
	u, d = hs.Ui('C'), data(mode='Stop', psp=0)
	assert u.press(d, NOW) == []                       # home -> menu
	assert u.press(d, NOW) == []                       # "Accendi" -> confirmation
	v = u.view(d, NOW)
	assert v['screen'] == 'confirm' and v['selected'] == 'cancel'
	assert u.press(d, NOW) == []                       # "Annulla"
	assert u.view(d, NOW)['screen'] == 'home'
	u.press(d, NOW); u.press(d, NOW)
	u.rotate(1, d, NOW)                                # -> "Accendi"
	assert u.press(d, NOW) == [('set', ['mode', 'startup', None, None])]


def test_touch_confirmation_buttons():
	u, d = hs.Ui('C'), data(mode='Hold')
	tap(u, d, 'menu')
	tap(u, d, 'item:2')                                # Spegnimento
	assert u.view(d, NOW)['screen'] == 'confirm'
	assert tap(u, d, 'ok') == [('set', ['mode', 'shutdown', None, None])]


def test_stop_asks_only_while_there_is_fire():
	u = hs.Ui('C')
	d = data(mode='Monitor')
	tap(u, d, 'menu')
	assert tap(u, d, 'item:1') == [('set', ['mode', 'stop', None, None])]
	for mode in ('Hold', 'Shutdown'):
		u, d = hs.Ui('C'), data(mode=mode)
		tap(u, d, 'menu')
		items = u.view(d, NOW)['items']
		tap(u, d, f'item:{[i["key"] for i in items].index("stop")}')
		assert u.view(d, NOW)['screen'] == 'confirm'


def test_smoke_and_monitor_go_straight():
	u, d = hs.Ui('C'), data(mode='Hold')
	tap(u, d, 'menu')
	assert tap(u, d, 'item:1') == [('set', ['mode', 'smoke', None, None])]


def test_idle_screens_go_back_home():
	u, d = hs.Ui('C'), data(mode='Hold')
	tap(u, d, 'menu')
	assert u.view(d, NOW + hs.IDLE_BACK_S - 1)['screen'] == 'menu'
	assert u.view(d, NOW + hs.IDLE_BACK_S + 1)['screen'] == 'home'


def test_back_arrow():
	u, d = hs.Ui('C'), data(mode='Hold')
	tap(u, d, 'menu')
	tap(u, d, 'back')
	assert u.view(d, NOW)['screen'] == 'home'


# ------------------------------------------------------------ emergency network and messages

def test_emergency_network_screen_while_the_grill_is_off():
	ap = {'state': 'ap', 'ap': {'ssid': 'PiFire-Setup', 'url': 'http://10.42.0.1', 'qr': 'WIFI:T:nopass;S:PiFire-Setup;;'}}
	u = hs.Ui('C')
	v = u.view(data(mode='Stop', wifi=ap), NOW)
	assert v['screen'] == 'wifi' and v['url'] == 'http://10.42.0.1' and v['qr'].startswith('WIFI:')
	assert u.touch(500, 300, data(mode='Stop', wifi=ap), NOW) == []          # no command from this screen
	assert u.view(data(mode='Stop', wifi=ap), NOW + 10)['screen'] == 'home'
	assert u.view(data(mode='Stop', wifi=ap), NOW + hs.WIFI_DISMISS_S + 1)['screen'] == 'wifi'
	assert hs.Ui('C').view(data(mode='Hold', wifi=ap), NOW)['screen'] == 'home'   # a lit grill keeps its screen
	assert hs.Ui('C').view(data(mode='Hold', wifi=ap), NOW)['wifi'] == 'ap'


def test_messages_from_the_control_process():
	u = hs.Ui('C')
	u.show_message('ERRORE', NOW)
	v = u.view(data(), NOW + 1)
	assert v['screen'] == 'message' and v['text'] == 'ERRORE' and v['note']
	assert u.view(data(), NOW + 9)['screen'] == 'home'


def test_presets_come_from_the_dashboard_setting():
	assert hs.parse_presets('Fumo:80, Arrosto:175', 'C') == [('Fumo', 80), ('Arrosto', 175)]
	assert hs.parse_presets('', 'F') == hs.DEFAULT_PRESETS['F']
	assert hs.parse_presets('nonsense', 'C') == hs.DEFAULT_PRESETS['C']


def test_fahrenheit_steps_and_limits():
	u = hs.Ui('F')
	u.rotate(1, data(psp=225), NOW)
	v = u.view(data(psp=225), NOW)
	assert v['value'] == 230 and (v['vmin'], v['vmax']) == (150, 500)


# ------------------------------------------------------------ system power off

def test_power_off_only_from_a_stopped_grill():
	assert 'poweroff' in hs.menu_keys('Stop')
	for mode in ('Startup', 'Smoke', 'Hold', 'Shutdown', 'Monitor', 'Recipe', 'Error'):
		assert 'poweroff' not in hs.menu_keys(mode)


def test_power_off_asks_first_and_then_says_when_to_pull_the_plug():
	u, d = hs.Ui('C'), data(mode='Stop', psp=0)
	tap(u, d, 'menu')
	tap(u, d, f'item:{hs.menu_keys("Stop").index("poweroff")}')
	v = u.view(d, NOW)
	assert v['screen'] == 'confirm' and v['selected'] == 'cancel'
	assert tap(u, d, 'cancel') == [] and u.view(d, NOW)['screen'] == 'home'
	u.press(d, NOW)                                    # menu
	u.rotate(2, d, NOW)                                # -> "Spegni sistema"
	u.press(d, NOW)                                    # confirmation
	u.rotate(1, d, NOW)                                # -> "Spegni"
	assert u.press(d, NOW) == [('poweroff', [])]
	v = u.view(d, NOW + 600)                           # stays, no idle timeout and no wifi screen
	assert v['screen'] == 'message' and v['text'] == 'SPEGNIMENTO' and 'staccare' in v['note']
	assert u.press(d, NOW) == [] and u.touch(500, 300, d, NOW) == []


def test_no_power_off_if_the_grill_was_started_meanwhile():
	u = hs.Ui('C')
	tap(u, data(mode='Stop'), 'menu')
	tap(u, data(mode='Stop'), f'item:{hs.menu_keys("Stop").index("poweroff")}')
	assert tap(u, data(mode='Startup'), 'ok') == []
	assert u.view(data(mode='Startup'), NOW)['screen'] == 'home'
