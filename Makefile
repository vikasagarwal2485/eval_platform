.PHONY: setup agents-setup dev run test lint format build

setup:            ## create the backend venv and install both stacks
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

agents-setup:      ## create a venv for the reference agents (only needed to run them standalone, elsewhere)
	cd agents && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

dev:              ## backend :8000 + frontend :5173 with hot reload
	./scripts/dev.sh

run:              ## build the UI and serve everything from one URL (:8000)
	./scripts/run.sh

test:
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npm run lint && npm run typecheck && npm run format:check

format:
	cd backend && .venv/bin/ruff check --fix app tests && .venv/bin/ruff format app tests
	cd frontend && npm run format

build:
	cd frontend && npm run build
