# backend/Makefile — build, test, lint, and package the FastAPI backend
#
# Usage:
#   make              # show available targets
#   make install      # install all dependencies
#   make test         # run the test suite
#   make docker       # build the container image

PYTHON         ?= python3
PIP            ?= pip
IMAGE          ?= vibe-coded-backend
TAG            ?= latest
DEV            ?= 1
SESSION_SECRET ?= dev-only-not-for-production

.PHONY: help install build test test-cov lint format clean docker dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime and test dependencies
	$(PIP) install -r requirements.txt -r tests/requirements.txt

build: ## Run Alembic migration check (verify heads)
	$(PYTHON) -m alembic check 2>/dev/null || $(PYTHON) -m alembic heads

test: ## Run the test suite
        DEV=$(DEV) SESSION_SECRET=$(SESSION_SECRET) \
        $(PYTHON) -m pytest tests/ -v --import-mode=importlib --cache-clear

test-cov: ## Run tests with coverage report
        DEV=$(DEV) SESSION_SECRET=$(SESSION_SECRET) \
        $(PYTHON) -m pytest tests/ -v --import-mode=importlib --cache-clear \
                --cov=. --cov-report=term-missing

lint: ## Lint with ruff (check + format)
        $(PYTHON) -m ruff check .
        $(PYTHON) -m ruff format --check .

format: ## Auto-format with ruff
	$(PYTHON) -m ruff format .

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .hypothesis .coverage htmlcov

docker: ## Build the Docker image
	docker build -t $(IMAGE):$(TAG) .

dev: ## Run the development server with auto-reload
	$(PYTHON) -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
