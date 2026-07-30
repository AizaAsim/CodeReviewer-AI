.PHONY: dev test migrate

dev:
	uv run uvicorn codereviewer.main:app --reload --port 8000

test:
	uv run pytest -q -m "not manual"

migrate:
	uv run alembic upgrade head

eval:
	uv run python eval/run_eval.py
