.DEFAULT_GOAL := help
.PHONY: help sync lock-check lint format format-check test ci hooks pre-commit run scrape fixtures

help: ## List targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-14s %s\n", $$1, $$2}'

sync: ## Install all dependencies
	uv sync --all-groups

lock-check: ## Fail if uv.lock is out of date
	uv lock --check

lint: ## Check code with ruff
	uv run ruff check .

format: ## Fix lint errors and format code
	uv run ruff check --fix .
	uv run ruff format .

format-check: ## Fail if code is not formatted
	uv run ruff format --check .

test: ## Run tests
	uv run pytest

ci: lock-check lint format-check test ## Everything GitHub Actions runs

hooks: ## Install the git pre-commit hooks
	uv run pre-commit install

pre-commit: ## Run the pre-commit hooks on all files
	uv run pre-commit run --all-files

run: ## Run the app
	uv run local-branch-overview

scrape: ## Scrape all districts to data/raw (slow, ~2-3 h, resumable)
	uv run scrape-branches

fixtures: ## Re-snapshot all districts + 2 branches each for tests (~10-15 min)
	uv run python scripts/refresh_fixtures.py
