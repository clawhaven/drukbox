# Drukbox API Tests

Black-box Playwright tests against an already-running `drukbox`. Everything
goes through the HTTP API — no browser, frontend, FastAPI internals, or direct
database access.

The suite provisions (and deletes) a real host, so point it at disposable
infrastructure.

## Run

```bash
SERVICE_URL=http://localhost:8780 \
SERVICE_TOKEN=<service-token> \
npm --prefix api-tests test
```

The suite reads `DEFAULT_HOST_PROVIDER` to assert the created host's provider,
and `<PROVIDER>_DEFAULT_IMAGE` (e.g. `DOCKER_DEFAULT_IMAGE`) to assert the
default image when `HOST_IMAGE` is unset. Other knobs, defaults in parentheses:

- `HOST_IMAGE` — image sent on create; omitted from the request if unset.
- `API_TIMEOUT_MS` (`30000`) — per-request and per-test timeout.
- `HOST_ACTIVE_TIMEOUT_MS` (`600000`) — how long to wait for a host to reach `active`.
- `HOST_POLL_INTERVAL_MS` (`5000`) — poll interval while waiting.
