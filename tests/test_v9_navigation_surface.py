from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_destinations_are_antarctic_only():
    r = client.get('/api/locations/antarctica')
    assert r.status_code == 200
    data = r.json()
    assert data['operational_latitude_limit'] == -45.0
    assert data['locations']
    assert all(float(x['lat']) <= -45.0 for x in data['locations'])
    names = ' '.join(x['name'] for x in data['locations']).lower()
    assert 'bharati station' in names
    assert 'maitri station' in names
    bharati = next(x for x in data['locations'] if x['id'] == 'bharati-station')
    maitri = next(x for x in data['locations'] if x['id'] == 'maitri-station')
    # Station coordinates are retained as verified references, but land-based
    # stations are not silently converted into marine route endpoints.
    assert bharati['routing_eligible'] is False
    assert maitri['routing_eligible'] is False


def test_route_rejects_origin_outside_antarctic_operational_area():
    payload = {
        'origin': {'lat': 19.0, 'lon': 72.0},
        'destination': {'lat': -67.0, 'lon': -45.0},
        'speed_kmh': 20,
        'safety_threshold_km': 30,
        'icebergs': [],
    }
    r = client.post('/api/navigation/optimize', json=payload)
    assert r.status_code == 400
    assert 'south of 45' in r.json()['error'].lower() or '45°s' in r.json()['error'].lower()


def test_route_reports_time_aware_geodesic_metadata():
    payload = {
        'origin': {'lat': -58.0, 'lon': -48.0},
        'destination': {'lat': -62.0, 'lon': -56.0},
        'speed_kmh': 20,
        'safety_threshold_km': 30,
        'icebergs': [],
    }
    r = client.post('/api/navigation/optimize', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['routing_method'] == 'TIME_AWARE_POLAR_ASTAR_GEODESIC_WITH_P90_ICEBERG_ENVELOPES'
    assert data['route_precision']['operational_area'] == 'south of 45°S'
    assert all('arrival_utc' in route for route in data['routes'])
