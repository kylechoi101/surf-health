PYTHON ?= python3.12

.PHONY: setup-backend dev-api test-backend lint-backend train-sample refresh-data

# web/ and mobile/ now live in separate private repos:
#   github.com/kylechoi101/shorelife-web
#   github.com/kylechoi101/shorelife-mobile
# This Makefile only covers the public backend + ML pipeline.

setup-backend:
	cd backend && $(PYTHON) -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"

dev-api:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

test-backend:
	cd backend && . .venv/bin/activate && pytest

lint-backend:
	cd backend && . .venv/bin/activate && ruff check app tests

train-sample:
	cd backend && . .venv/bin/activate && python -m app.ml.training --sample-fixture

refresh-data:
	@echo "Running full pipeline + training..."
	cd backend && . .venv/bin/activate && \
	  python -m app.data.pipeline.cli --normalize-beachwatch \
	    --stations-csv /tmp/stations.csv \
	    --merge-ceden --with-external-covariates --with-hydrology && \
	  python -m app.ml.training --curated --forecast-date $$(date +%Y-%m-%d)
	@echo "Staging data/curated/ for commit..."
	git add data/curated/
	@echo "Done. Review with 'git diff --staged' then commit."

