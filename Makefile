.PHONY: default
default: check lint

.venv:
	make install-dev

.PHONY: install-dev
install-dev:
	uv python install
	uv sync --all-extras --dev

# Mypy is a static type checker for Python.
# https://mypy.readthedocs.io/
.PHONY: check
check: .venv
	uv run mypy src

# An extremely fast Python linter and code formatter, written in Rust.
# https://docs.astral.sh/ruff/
.PHONY: lint
lint: .venv
	uv run ruff check

.PHONY: format
format: .venv
	uv run ruff format

.PHONY: test
test: .venv
	uv run pytest

.PHONY: test-cov
test-cov: .venv
	uv run pytest --cov=gnlog --cov-report=html

.PHONY: test-watch
test-watch: .venv
	uv run pytest --watch

.PHONY: git-check
git-check: git-check-uncommited-changes git-check-untracked-files

.PHONY: git-check-uncommited-changes
git-check-uncommited-changes:
	@git diff --exit-code > /dev/null && \
		echo "no uncommited changes" || \
		( echo "uncommited changes exists" && git diff && exit 1 )

GIT_CHECK_UNTRACKED_FILES := $(shell git ls-files . --exclude-standard --others)

.PHONY: git-check-untracked-files
git-check-untracked-files:
	@if [ "$(GIT_CHECK_UNTRACKED_FILES)" = "" ]; then \
	  echo "No untracked file" ; \
	else \
	  echo "There is untracked file(s): $(GIT_CHECK_UNTRACKED_FILES)" && git status && exit 1 ; \
	fi
