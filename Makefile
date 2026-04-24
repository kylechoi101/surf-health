PYTHON ?= python3.12

.PHONY: setup-backend setup-web dev-api dev-web test-backend lint-backend train-sample

setup-backend:
	cd backend && $(PYTHON) -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"

setup-web:
	cd web && npm install

dev-api:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

test-backend:
	cd backend && . .venv/bin/activate && pytest

lint-backend:
	cd backend && . .venv/bin/activate && ruff check app tests

train-sample:
	cd backend && . .venv/bin/activate && python -m app.ml.training --sample-fixture

