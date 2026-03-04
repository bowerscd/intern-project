# vibe-integrated

Integration and end-to-end tests for the full-stack application (backend + frontend + mock OIDC).

## Architecture

Tests spin up real instances of:
- **Mock OIDC provider** (`mock_oidc.py`) — full Authorization Code flow
- **FastAPI backend** (from `../vibe-coded`)
- **Flask frontend** (from `../vibe-coded-front-end`)

All services communicate over HTTP on `localhost` with random ports.  
No mocking — requests go through the actual network stack.

## Running

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run all integration tests
pytest -v

# With coverage
pytest --cov --cov-report=term-missing
```

### Playwright setup

Some tests use Playwright to drive a real Chromium browser through the UI.
If Playwright is not installed, those tests are automatically skipped.

```bash
# One-time setup: install Playwright + Chromium
pip install -r requirements.txt
playwright install --with-deps chromium
```

If Playwright is not installed, browser-based tests are automatically skipped.

## Test categories

| Module | Covers |
|---|---|
| `test_e2e_oidc.py` | Full OIDC Authorization Code flow through the backend |
| `test_e2e_auth_gate.py` | Frontend auth gate redirect behaviour with real backend |
| `test_security.py` | XSS, CSRF, session hijacking, OIDC replay |
| `test_contract.py` | API schema & OpenAPI contract validation |
| `test_resilience.py` | Backend/OIDC unavailability, timeout handling |
| `test_browser_smoke.py` | Playwright — page rendering, nav, static assets |
| `test_browser_oidc_flow.py` | Playwright — full OIDC registration through the browser UI |

## Environment

The `conftest.py` module starts/stops all servers automatically via fixtures.
Port allocation is dynamic (bind to port 0) so tests never conflict.
