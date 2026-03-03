# integration-tests/Makefile — run integration & E2E tests
#
# Usage:
#   make              # show available targets
#   make install      # install test dependencies locally
#   make test         # bring up Docker stack and run tests
#   make test-local   # run tests with local processes (no Docker)

PYTHON       ?= python3
PIP          ?= pip
COMPOSE      ?= docker compose
BACKEND_URL  ?= http://127.0.0.1:8000
FRONTEND_URL ?= http://127.0.0.1:5000

# Force Docker image format so HEALTHCHECK works under Podman (OCI format ignores it)
export BUILDAH_FORMAT ?= docker

.PHONY: help install install-browser test test-local test-browser up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install test dependencies (Python packages + Playwright Chromium)
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install --with-deps chromium

install-browser: install ## Alias for install (Playwright now included by default)

up: ## Start the Docker Compose stack and wait for all services to be healthy
	mkdir -p backend-data
	chmod 777 backend-data
	$(COMPOSE) up --build --wait -d

down: ## Stop the Docker Compose stack
	$(COMPOSE) down

test: up ## Run integration tests via Docker Compose (all tests, including browser)
	BACKEND_URL=$(BACKEND_URL) FRONTEND_URL=$(FRONTEND_URL) \
	BACKEND_DB_PATH=$(CURDIR)/backend-data/app.db \
	$(PYTHON) -m pytest . -v --timeout=60; \
	status=$$?; \
	$(COMPOSE) down; \
	exit $$status

test-local: ## Run integration tests with local processes (no browser tests)
	$(PYTHON) -m pytest . -v --timeout=60 -m "not browser"

test-browser: ## Run only Playwright browser tests (local processes)
	$(PYTHON) -m pytest . -v --timeout=60 -m browser

test-all: ## Run all tests including browser tests (local processes)
	$(PYTHON) -m pytest . -v --timeout=60

clean: ## Tear down stack, remove volumes, and delete local DB
	$(COMPOSE) down -v --remove-orphans
	rm -rf backend-data
