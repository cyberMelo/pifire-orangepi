'''
Wizard: deleting a probe device also deletes the probes on its ports.  On the
board that left a grill with no probes and the Settings page failed
(probe_info[0] of an empty list), so the wizard now refuses to finish
without a Primary probe.
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
pytest.importorskip('flask')

from blueprints.wizard.wizard import missing_probe_types  # noqa: E402


def test_primary_probe_is_required():
	assert missing_probe_types({'probe_devices': [{'device': 'Prototype'}], 'probe_info': []}) == ['Primary']
	assert missing_probe_types({'probe_info': [{'label': 'Probe1', 'type': 'Food'}]}) == ['Primary']
	assert missing_probe_types({'probe_info': [{'label': 'Grill', 'type': 'Primary'},
											   {'label': 'Probe1', 'type': 'Food'}]}) == []
	assert missing_probe_types({}) == ['Primary']
