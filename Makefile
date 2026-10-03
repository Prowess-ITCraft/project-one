# Linux/macOS and CI. On Windows use scripts/dev.ps1 (same commands, no make needed).
COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev --profile monitoring
PY = backend/.venv/bin/python

.PHONY: up down logs ps build test lint typecheck lint-imports migrate seed admin openapi backup

up: ; $(COMPOSE_DEV) up -d --build
down: ; $(COMPOSE_DEV) down
logs: ; $(COMPOSE_DEV) logs -f --tail=100
ps: ; $(COMPOSE_DEV) ps
build: ; $(COMPOSE_DEV) build
test: ; cd backend && $(PY) -m pytest -q --cov=app
lint: ; cd backend && $(PY) -m ruff check app tests && $(PY) -m ruff format --check app tests
typecheck: ; cd backend && $(PY) -m mypy app tests
lint-imports: ; cd backend && $(PY) -m importlinter.cli --config ../.importlinter || lint-imports --config ../.importlinter
migrate: ; $(COMPOSE_DEV) run --rm migrate
seed: ; $(COMPOSE_DEV) exec api python -m app.cli seed
admin: ; $(COMPOSE_DEV) exec api python -m app.cli create-admin --email $(EMAIL) --name "$(NAME)" --initials $(INITIALS)
openapi: ; cd backend && $(PY) -m app.cli openapi --out openapi.json
backup: ; $(COMPOSE_DEV) exec worker python -m app.cli backup
