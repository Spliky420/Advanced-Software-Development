"""Release 2: two Transactions backend endpoint functions, no live services required."""
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def backend(monkeypatch, tmp_path):
    # Run from repository root: PYTHONPATH=thomas-backend pytest -q
    import app as module
    monkeypatch.setattr(module, 'DATABASE', str(tmp_path / 'test_transactions.db'))
    module.init_db()
    connection = module.get_db()
    connection.executemany(
        """INSERT INTO transactions
        (transaction_date,merchant,description,amount,transaction_type,category,deduction_status)
        VALUES (?,?,?,?,?,?,?)""",
        [
            ('2026-10-01','Employer','Salary',3750,'income','income','not_reviewed'),
            ('2026-10-02','Officeworks','Supplies',100,'expense','work','potentially_deductible'),
            ('2026-10-03','Cafe','Lunch',25,'expense','other','not_deductible'),
        ],
    )
    connection.commit()
    connection.close()
    module.app.config['TESTING'] = True
    return module


def test_get_transactions_filters_by_merchant(backend):
    """Endpoint function 1: get_transactions."""
    response = backend.app.test_client().get('/api/transactions?search=Officeworks')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Officeworks' in body
    assert 'Employer' not in body
    assert 'Cafe' not in body


def test_start_multi_agent_sends_verified_sql_evidence(backend, monkeypatch):
    """Endpoint function 2: start_multi_agent, with HTTP mocked."""
    captured = {}
    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['payload'] = kwargs['json']
        result = Mock(status_code=202)
        result.json.return_value = {'run_id':'test-run-1', 'status':'planning'}
        return result
    monkeypatch.setattr(backend.requests, 'post', fake_post)
    response = backend.app.test_client().post('/api/transactions/multi-agent')
    assert response.status_code == 202
    assert response.get_json()['run_id'] == 'test-run-1'
    assert captured['url'].endswith('/workflow')
    assert captured['payload']['caller'] == 'Thomas'
    assert captured['payload']['evidence'] == {
        'transaction_count': 3,
        'total_income': 3750.0,
        'total_expenses': 125.0,
        'potential_deductions': 100.0,
    }
    # For asynchronous shared server, also assert:
    # assert captured['payload']['async'] is True
