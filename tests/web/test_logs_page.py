'''
Logs page: the "Choose..." placeholder is not a file (on the board it logged
"Unable to open log file: ./logs/Choose..."), and only listed log files can be
shown or downloaded.
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
flask = pytest.importorskip('flask')


@pytest.fixture
def client(tmp_path, monkeypatch):
	from blueprints.logs import logs_bp, routes
	logs = tmp_path / 'logs'
	logs.mkdir()
	(logs / 'control.log').write_text('2026-10-30 15:43:28 [INFO] Stop Mode Started.\n')
	(logs / 'notes.txt').write_text('not a log\n')
	opened = []
	monkeypatch.setattr(routes, 'read_settings', lambda: {'globals': {}})
	monkeypatch.setattr(routes, 'read_control', lambda: {})
	monkeypatch.setattr(routes, 'read_log_file', lambda path: opened.append(path) or open(path).readlines())
	app = flask.Flask(__name__, template_folder=os.path.join(ROOT, 'templates'))
	app.config.update(LOGS_FOLDER=str(logs) + '/', ALLOWED_EXTENSIONS={'log', 'json'})
	app.register_blueprint(logs_bp)
	client = app.test_client()
	client.opened = opened
	return client


def _events(client, name):
	return client.post('/logs/', data={'eventslist': 'true', 'logfile': name, 'page': '1',
									   'reverse': 'false', 'itemsperpage': '10'})


def test_placeholder_is_not_opened(client):
	for name in ('Choose...', '', '../settings.json', 'notes.txt'):
		response = _events(client, name)
		assert response.status_code == 200 and b'Select a log' in response.data
	assert client.opened == []


def test_listed_log_is_shown(client):
	response = _events(client, 'control.log')
	assert response.status_code == 200 and b'Stop Mode Started' in response.data
	assert len(client.opened) == 1


def test_download_only_listed_files(client):
	assert client.post('/logs/', data={'download': 'true', 'selectLog': 'Choose...'}).status_code == 400
	ok = client.post('/logs/', data={'download': 'true', 'selectLog': 'control.log'})
	assert ok.status_code == 200 and b'Stop Mode' in ok.data
