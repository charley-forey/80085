.PHONY: dev up down worker api test test-unit test-integration test-security test-e2e lint typecheck migrate seed benchmark capabilities

up:            ; docker compose up -d
down:          ; docker compose down
dev: up migrate ; @echo "services up + migrated. run 'make api' and 'make worker' in separate shells."
api:           ; uv run uvicorn boobs_api.main:app --reload --port 8000
worker:        ; uv run 80085-worker
migrate:       ; uv run alembic upgrade head
seed:          ; uv run python scripts/seed.py
capabilities:  ; uv run python scripts/build_capabilities.py
test:          ; uv run pytest tests/unit tests/integration -q
test-unit:     ; uv run pytest tests/unit -q
test-integration: ; uv run pytest tests/integration -q
test-security: ; uv run pytest tests/security -v
test-e2e:      ; uv run pytest tests/e2e -v
lint:          ; uv run ruff check . && uv run ruff format --check .
typecheck:     ; uv run mypy packages apps
benchmark:     ; uv run python benchmarks/run.py
