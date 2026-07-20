.PHONY: install check tests

install:
	uv sync --all-groups --all-extras

check:
	uv run ruff format --check .
	uv run ruff check .
	uv run ty check

tests: check
	uv run pytest --cov=clitg --cov-branch --cov-report=term-missing --cov-fail-under=100
