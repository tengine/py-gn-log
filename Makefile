.PHONY: default
default: check lint

# Mypy is a static type checker for Python.
# https://mypy.readthedocs.io/
.PHONY: check
check:
	uv run mypy src

# An extremely fast Python linter and code formatter, written in Rust.
# https://docs.astral.sh/ruff/
.PHONY: lint
lint:
	uv run ruff check

.PHONY: format
format:
	uv run ruff format
