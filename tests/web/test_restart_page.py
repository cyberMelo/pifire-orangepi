'''
Restart page (templates/shutdown.html): after an OTA update it sent the browser
to the dashboard as soon as the web app was back, a few seconds before the
control process; the dashboard then showed "The control process did not respond"
(board, 2026-11-17).  The page now also waits for /api/sys/check_alive, at most
a fixed time, then goes to the dashboard anyway.
'''

import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
flask = pytest.importorskip('flask')

PAGE = os.path.join(ROOT, 'templates', 'shutdown.html')


@pytest.fixture
def api(monkeypatch):
	from blueprints.api import api_bp, routes
	state = {'alive': False, 'asked': []}
	monkeypatch.setattr(routes, 'read_settings', lambda: {})
	monkeypatch.setattr(routes, 'get_server_status', lambda: 'available')
	monkeypatch.setattr(routes, 'process_command', lambda action, arglist, origin: state['asked'].append((action, arglist[0])))

	def output(requested):
		if state['alive']:
			return {'command': [requested, None, None, None], 'result': 'OK', 'message': '', 'data': {}}
		return {'command': [requested, None, None, None], 'result': 'ERROR', 'message': 'not found', 'data': {}}
	monkeypatch.setattr(routes, 'get_system_command_output', output)
	app = flask.Flask(__name__)
	app.register_blueprint(api_bp)
	client = app.test_client()
	client.state = state
	return client


def test_check_alive_reports_whether_control_answers(api):
	''' The contract the restart page relies on '''
	assert api.get('/api/sys/check_alive').get_json()['result'] == 'ERROR'
	api.state['alive'] = True
	assert api.get('/api/sys/check_alive').get_json()['result'] == 'OK'
	assert api.state['asked'] == [('sys', 'check_alive'), ('sys', 'check_alive')]


def _script():
	text = open(PAGE, encoding='utf-8').read()
	return text[text.index('{% block scripts %}'):]


def test_dashboard_waits_for_the_control_process():
	script = _script()
	assert '/api/server' in script and '/api/sys/check_alive' in script
	# the only redirect to the dashboard is inside the check_alive answer, behind its condition
	redirects = [m.start() for m in re.finditer(r"location\.href\s*=\s*'/'", script)]
	assert len(redirects) == 1
	before = script[:redirects[0]]
	assert before.rfind('/api/sys/check_alive') > before.rfind('/api/server')
	assert re.search(r"if \(alive\.result == 'OK' \|\| Date\.now\(\) - serverBackAt > CONTROL_WAIT_MS\)\s*\{\s*$", before)


def test_waits_a_bounded_time_and_polls_one_request_at_a_time():
	script = _script()
	wait = int(re.search(r'CONTROL_WAIT_MS = (\d+);', script).group(1))
	assert 10000 <= wait <= 120000   # longer than the control start-up, short enough to show a real failure
	assert 'setInterval' not in script   # check_alive can take 3 s: no overlapping requests
