.PHONY: help setup db ingest api web test lint mcp licenses clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## create the venv and install the backend
	cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"

db:  ## start Postgres and create the schema
	docker compose up -d db
	cd backend && .venv/bin/python -m qra.cli initdb

licenses:  ## print the licensing audit
	cd backend && .venv/bin/python -m qra.cli licenses

ingest:  ## load the corpus (downloads are cached under data/raw)
	cd backend && .venv/bin/python -m qra.cli ingest

api:  ## run the API on :8000
	cd backend && .venv/bin/python -m qra.cli serve --reload

mcp:  ## run the MCP server on stdio
	cd backend && .venv/bin/python -m qra.cli mcp

web:  ## run the frontend on :3000
	cd frontend && npm run dev

test:  ## run the test suite
	cd backend && .venv/bin/python -m pytest -q

lint:  ## ruff
	cd backend && .venv/bin/python -m ruff check qra tests

clean:  ## drop cached downloads
	rm -rf data/raw
