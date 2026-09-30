import logging

from app import main


def _access_records(caplog):
    return [r for r in caplog.records if r.name == "drd.access"]


def test_health_reports_ok_when_database_is_reachable(anon):
    response = anon.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_is_down(anon, monkeypatch):
    def broken_connect():
        raise ConnectionError("db down")
    monkeypatch.setattr(main.engine, "connect", broken_connect)
    response = anon.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_one_access_log_line_per_request(anon, caplog):
    with caplog.at_level(logging.INFO, logger="drd.access"):
        anon.get("/health")
    [record] = _access_records(caplog)
    assert record.fields["method"] == "GET"
    assert record.fields["path"] == "/health"
    assert record.fields["status"] == 200
    assert record.fields["duration_ms"] >= 0
    assert record.fields["user_id"] is None


def test_access_log_formats_as_json():
    from app.access_log import JsonFormatter
    record = logging.LogRecord("drd.access", logging.INFO, __file__, 1, "request", None, None)
    record.fields = {"method": "GET", "status": 200}
    import json
    line = json.loads(JsonFormatter().format(record))
    assert line["method"] == "GET" and line["status"] == 200 and line["msg"] == "request"
