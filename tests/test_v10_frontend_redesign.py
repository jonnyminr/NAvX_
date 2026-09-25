from fastapi.testclient import TestClient

from src.api.main import app


client = TestClient(app)


def test_redesigned_frontend_pages_and_integrity_labels_present():
    html = client.get('/').text
    required = [
        'homeSection', 'mapSection', 'forecastSection', 'plannerSection',
        'graphSection', 'riskDashboard', 'dataObservatory', 'riskDetails',
        'alertsSection', 'scenarioSection', 'historicalSection',
        'icebergCatalog', 'vesselCatalog', 'settingsSection',
    ]
    for page_id in required:
        assert f'id="{page_id}"' in html
    assert 'No simulated AIS or iceberg observations' in html
    assert 'MODEL OUTPUT · not observation' in html


def test_archived_iceberg_replay_uses_official_snapshot_files_only():
    payload = client.get('/api/data/icebergs/archive').json()
    assert payload['data_type'] == 'ARCHIVED_OFFICIAL_SNAPSHOTS'
    assert 'no synthetic interpolation' in payload['scientific_integrity'].lower()
    assert payload['snapshot_count'] >= 1
    for snapshot in payload['snapshots']:
        assert snapshot['count'] == len(snapshot['icebergs']['features'])
        for feature in snapshot['icebergs']['features']:
            assert feature['properties']['position_type'] == 'OFFICIAL_USNIC_TABLE_FIX'
