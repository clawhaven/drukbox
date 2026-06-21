import logging

from api.app import _HealthzAccessFilter


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_access_log_is_dropped_but_other_paths_pass():
    """The /healthz probe is filtered out of the access log; real traffic isn't."""
    access_filter = _HealthzAccessFilter()

    def access_record(request_line: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s" %d',
            ("127.0.0.1:5000", request_line, 200),
            None,
        )

    assert access_filter.filter(access_record("GET /healthz HTTP/1.1")) is False
    assert access_filter.filter(access_record("GET /hosts HTTP/1.1")) is True
