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
        lint lint-backend lint-frontend format clean install-hooks

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
