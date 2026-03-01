# integration-tests/Makefile — run integration & E2E tests
#
# Usage:
#   make              # show available targets
#   make install      # install test dependencies locally
#   make test         # bring up Docker stack and run tests
#   make test-local   # run tests with local processes (no Docker)

PYTHON  ?= python3
PIP     ?= pip
COMPOSE ?= docker compose

.PHONY: help install test test-local up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install test dependencies
	$(PIP) install -r requirements.txt

up: ## Start the Docker Compose stack (build images first)
	$(COMPOSE) up --build -d

down: ## Stop the Docker Compose stack
	$(COMPOSE) down

test: up ## Run integration tests via Docker Compose
	$(PYTHON) -m pytest . -v --timeout=60; \
	status=$$?; \
	$(COMPOSE) down; \
	exit $$status

test-local: ## Run integration tests with local processes (no Docker)
	$(PYTHON) -m pytest . -v --timeout=60

clean: ## Tear down stack and remove volumes
	$(COMPOSE) down -v --remove-orphans
