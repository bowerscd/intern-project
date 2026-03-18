# Root Makefile — one-command setup and orchestration for all services
#
# Usage:
#   make              # show available targets
#   make setup        # create venvs + install ALL dependencies (Python & Node)
#   make test         # run backend + frontend tests
#   make lint         # lint all projects
#   make clean        # remove caches and build artifacts
#
# Each service has its own venv under <service>/.venv so that
# dependencies stay isolated (backend ≠ frontend ≠ integration-tests).

PYTHON ?= python3
COMPOSE ?= podman-compose

# Venv interpreters — used internally by sub-makes
BACKEND_VENV      := backend/.venv/bin
FRONTEND_VENV     := frontend/.venv/bin
INTEGRATION_VENV  := integration-tests/.venv/bin

.PHONY: help setup setup-backend setup-frontend setup-integration \
        test test-backend test-frontend test-integration test-integration-local \
        lint lint-backend lint-frontend format clean install-hooks \
        dev dev-stop dev-logs

# ─── Help ─────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ─── Setup (venvs + dependencies) ────────────────────────────────────────────

setup: setup-backend setup-frontend setup-integration install-hooks ## Create all venvs, install deps, and configure git hooks
	@printf '\n  \033[32m✔ All environments ready.\033[0m\n\n'

setup-backend: $(BACKEND_VENV)/activate ## Set up backend venv + deps
	$(BACKEND_VENV)/pip install -r backend/requirements.txt -r backend/tests/requirements.txt
	@printf '  \033[32m✔ backend\033[0m\n'

setup-frontend: $(FRONTEND_VENV)/activate ## Set up frontend venv + deps (Python & Node)
	$(FRONTEND_VENV)/pip install -r frontend/requirements.txt -r frontend/tests/requirements.txt
	cd frontend && npm install
	@printf '  \033[32m✔ frontend\033[0m\n'

setup-integration: $(INTEGRATION_VENV)/activate ## Set up integration-tests venv + deps
	$(INTEGRATION_VENV)/pip install -r integration-tests/requirements.txt
	@printf '  \033[32m✔ integration-tests\033[0m\n'

# Create venvs on demand (only if missing)
%/.venv/bin/activate:
	$(PYTHON) -m venv $*/.venv

# ─── Tests ────────────────────────────────────────────────────────────────────

test: test-backend test-frontend test-integration ## Run all tests

test-backend: ## Run backend tests
	cd backend && $(CURDIR)/$(BACKEND_VENV)/python -m pytest tests/ -v --import-mode=importlib --cache-clear

test-frontend: ## Run frontend Python + TypeScript tests
	cd frontend && $(CURDIR)/$(FRONTEND_VENV)/python -m pytest tests/ -v
	cd frontend && npx vitest run

test-integration: ## Run integration tests (Docker/Podman stack)
	COMPOSE=$(COMPOSE) $(MAKE) -C integration-tests test

test-integration-local: ## Run integration tests against local processes (no Docker)
	PYTHON=$(CURDIR)/$(INTEGRATION_VENV)/python $(MAKE) -C integration-tests test-local

test-visual: ## Run visual approval tests (screenshots for human review)
	cd integration-tests && RUN_VISUAL_TESTS=1 $(CURDIR)/$(INTEGRATION_VENV)/python -m pytest \
		test_visual_approval.py -v --screenshots-dir=./screenshots/$$(date +%Y%m%d_%H%M%S)

test-stress: ## Run stress/load tests (requires running backend — use make dev first)
	cd integration-tests && $(CURDIR)/$(INTEGRATION_VENV)/python -m locust \
		-f test_stress.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000

test-stress-ui: ## Run stress tests with Locust web UI on http://localhost:8089
	cd integration-tests && $(CURDIR)/$(INTEGRATION_VENV)/python -m locust \
		-f test_stress.py --host http://127.0.0.1:8000

# ─── Lint / Format ───────────────────────────────────────────────────────────

lint: lint-backend lint-frontend ## Lint all projects

lint-backend: ## Lint backend with ruff
	cd backend && $(CURDIR)/$(BACKEND_VENV)/python -m ruff check .
	cd backend && $(CURDIR)/$(BACKEND_VENV)/python -m ruff format --check .

lint-frontend: ## Lint frontend (ruff + tsc --noEmit)
	cd frontend && $(CURDIR)/$(FRONTEND_VENV)/python -m ruff check .
	cd frontend && $(CURDIR)/$(FRONTEND_VENV)/python -m ruff format --check .
	cd frontend && npx tsc -p tsconfig.json --noEmit

format: ## Auto-format all Python code
	cd backend && $(CURDIR)/$(BACKEND_VENV)/python -m ruff format .
	cd frontend && $(CURDIR)/$(FRONTEND_VENV)/python -m ruff format .

# ─── Git Hooks ────────────────────────────────────────────────────────────────

install-hooks: ## Install the pre-commit git hook
	git config core.hooksPath .githooks
	chmod +x .githooks/*
	@printf '  \033[32m✔ git hooks installed (.githooks/)\033[0m\n'

# ─── Clean ────────────────────────────────────────────────────────────────────

clean: ## Remove caches and build artifacts (keeps venvs)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.hypothesis backend/.coverage
	rm -rf frontend/.pytest_cache frontend/.ruff_cache frontend/static/dist
	rm -rf integration-tests/.pytest_cache

clean-all: clean ## Clean + remove all venvs
	rm -rf backend/.venv frontend/.venv integration-tests/.venv

# ─── Local Dev Servers ────────────────────────────────────────────────────────

DEV_LOGS := .dev-logs

dev: ## Start backend + mock OIDC + frontend for local development
	@mkdir -p $(DEV_LOGS)
	@# Build TypeScript first
	cd frontend && npx tsc -p tsconfig.json
	@# Start mock OIDC provider and wait until it's reachable
	cd integration-tests && MOCK_OIDC_ISSUER=http://127.0.0.1:9000 \
	  nohup $(CURDIR)/$(INTEGRATION_VENV)/python mock_oidc.py 9000 \
	  > $(CURDIR)/$(DEV_LOGS)/oidc.log 2>&1 &
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
	  curl -sf http://127.0.0.1:9000/.well-known/openid-configuration > /dev/null 2>&1 && break; \
	  sleep 0.5; \
	done
	@curl -sf http://127.0.0.1:9000/.well-known/openid-configuration > /dev/null 2>&1 \
	  || { printf '  \033[31m✘ Mock OIDC failed to start on :9000\033[0m\n'; exit 1; }
	@# Start backend (in-memory DB, dev admin auto-seeded)
	cd backend && \
	  DEV=true SERVER_HOSTNAME=localhost \
	  TEST_OIDC_ISSUER=http://127.0.0.1:9000 \
	  TEST_CLIENT_ID=client_id1 \
	  TEST_CLIENT_SECRET=definitely_a_secret \
	  TEST_REDIRECT_URI=http://127.0.0.1:5000/api/v2/auth/callback/test \
	  GOOGLE_REDIRECT_URI=http://unused \
	  GOOGLE_CLIENT_SECRET=unused \
	  GOOGLE_CLIENT_ID=unused \
	  RATELIMIT_ENABLED=false \
	  nohup $(CURDIR)/$(BACKEND_VENV)/python -m uvicorn app:app \
	    --host 127.0.0.1 --port 8000 --log-level info \
	  > $(CURDIR)/$(DEV_LOGS)/backend.log 2>&1 &
	@sleep 0.5
	@# Start frontend
	cd frontend && \
	  SERVER_HOSTNAME=localhost DEV=true \
	  BACKEND_HOSTNAME=127.0.0.1 BACKEND_PORT=8000 \
	  nohup $(CURDIR)/$(FRONTEND_VENV)/python -m flask --app app run \
	    --host 127.0.0.1 --port 5000 \
	  > $(CURDIR)/$(DEV_LOGS)/frontend.log 2>&1 &
	@sleep 0.3
	@printf '\n  \033[32m✔ Dev servers running:\033[0m\n'
	@printf '    Frontend:  http://127.0.0.1:5000\n'
	@printf '    Backend:   http://127.0.0.1:8000\n'
	@printf '    Mock OIDC: http://127.0.0.1:9000\n'
	@printf '    Admin:     sub=dev-admin  username=admin\n'
	@printf '    Logs:      $(DEV_LOGS)/  (use \033[36mmake dev-logs\033[0m to tail)\n\n'
	@printf '  Run \033[36mmake dev-stop\033[0m to shut down all servers.\n\n'

dev-logs: ## Tail all dev server logs
	@tail -f $(DEV_LOGS)/backend.log $(DEV_LOGS)/frontend.log $(DEV_LOGS)/oidc.log

dev-stop: ## Stop all dev servers started by 'make dev'
	@pkill -f "python.*[m]ock_oidc.py 9000" 2>/dev/null || true
	@pkill -f "python.*[u]vicorn app:app.*--port 8000" 2>/dev/null || true
	@pkill -f "python.*[f]lask --app app run.*--port 5000" 2>/dev/null || true
	@printf '  \033[32m✔ Dev servers stopped.\033[0m\n'
	@printf '  Logs preserved in $(DEV_LOGS)/\n'
