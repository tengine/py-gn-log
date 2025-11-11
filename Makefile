.PHONY: default
default: check

# Mypy is a static type checker for Python.
# https://mypy.readthedocs.io/
.PHONY: check
check:
	uv run mypy src
