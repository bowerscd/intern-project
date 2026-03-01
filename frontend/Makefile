# frontend/Makefile — build, test, lint, and package the Flask frontend
#
# Usage:
#   make              # show available targets
#   make install      # install all dependencies
#   make test         # run Python + TypeScript tests
#   make docker       # build the container image

PYTHON      ?= python3
PIP         ?= pip
NPM         ?= npm
TSC         ?= npx tsc
OPENAPI_URL ?= http://localhost:8000/openapi.json
IMAGE       ?= vibe-coded-frontend
TAG         ?= latest

.PHONY: help install build generate-openapi dev \
        test test-py test-py-cov test-ts test-ts-cov \
        lint format clean docker

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and Node dependencies
	$(PIP) install -r requirements.txt -r tests/requirements.txt
	$(NPM) install

build: ## Compile TypeScript to static/dist
	$(TSC) -p tsconfig.json

generate-openapi: ## Regenerate the OpenAPI client
	OPENAPI_URL=$(OPENAPI_URL) $(PYTHON) scripts/generate_openapi_client.py

dev: ## Run the Flask development server
	FLASK_APP=app.py FLASK_DEBUG=1 flask run --port 5001

test-py: ## Run Python tests only
	$(PYTHON) -m pytest tests/ -v

test-py-cov: ## Run Python tests with coverage
	$(PYTHON) -m pytest tests/ --cov=app --cov-report=term-missing

test-ts: ## Run TypeScript (vitest) tests only
	npx vitest run

test-ts-cov: ## Run TypeScript tests with coverage
	npx vitest run --coverage

test: test-py test-ts ## Run all tests (Python + TypeScript)

lint: ## Lint Python (ruff) and TypeScript (tsc --noEmit)
	$(PYTHON) -m ruff check .
	$(TSC) -p tsconfig.json --noEmit

format: ## Auto-format Python code with ruff
	$(PYTHON) -m ruff format .

clean: ## Remove build artifacts and caches
	rm -rf static/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov node_modules/.cache

docker: ## Build the Docker image
	docker build -t $(IMAGE):$(TAG) .
