.DEFAULT_GOAL := help
.PHONY: help sync hooks lint format format-check test lock-check pre-commit ci run scrape fixtures

# `##@ Name` starts a group in `make help`; `target: ## text` lists a target in it.
help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@/ {printf "\n%s\n", substr($$0, 5); next} \
		/^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Setup

sync: ## Install all dependencies
	uv sync --all-groups

hooks: ## Install the git pre-commit hooks
	uv run pre-commit install

##@ Code quality

lint: ## Check code with ruff
	uv run ruff check .

format: ## Fix lint errors and format code
	uv run ruff check --fix .
	uv run ruff format .

format-check: ## Fail if code is not formatted
	uv run ruff format --check .

test: ## Run tests
	uv run pytest

lock-check: ## Fail if uv.lock is out of date
	uv lock --check

pre-commit: ## Run the pre-commit hooks on all files
	uv run pre-commit run --all-files

ci: lock-check lint format-check test ## Everything GitHub Actions runs

##@ App

run: ## Run the app
	uv run local-branch-overview

##@ Data

scrape: ## Scrape all districts to data/raw (slow, ~2-3 h, resumable)
	uv run scrape-branches

fixtures: ## Re-snapshot all districts + 2 branches each for tests (~10-15 min)
	uv run python scripts/refresh_fixtures.py
