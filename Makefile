.PHONY: default
default: check lint

.PHONY: clean
clean:
	rm -rf \
		.mypy_cache \
		.ruff_cache \
		dist \
		.venv \
		uv.lock

.venv:
	make install-dev

.PHONY: install-dev
install-dev:
	uv python install
	uv sync --all-extras --dev


PROJECT_NAME=$(shell uvx tomlq -r '.project.name' pyproject.toml | tr '-' '_')
PROJECT_VERSION=$(shell uvx tomlq -r '.project.version' pyproject.toml)
PYTHON_VERSION=$(shell cat .python-version)

VENV_SITE_PACKAGES=.venv/lib/python$(PYTHON_VERSION)/site-packages
VENV_EDITABLE_PATH=$(VENV_SITE_PACKAGES)/__editable__.$(PROJECT_NAME)-$(PROJECT_VERSION).pth

.PHONY: vars
vars:
	@echo "Project Name: $(PROJECT_NAME)"
	@echo "Project Version: $(PROJECT_VERSION)"
	@echo "Python Version: $(PYTHON_VERSION)"
	@echo ".venv Site-Packages: $(VENV_SITE_PACKAGES)"
	@echo ".venv Editable Path: $(VENV_EDITABLE_PATH)"

$(VENV_EDITABLE_PATH):
	make install-editable

.PHONY: install-editable
install-editable: .venv
	uv pip install --editable .

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
test: $(VENV_EDITABLE_PATH)
	uv run pytest

.PHONY: test-cov
test-cov: $(VENV_EDITABLE_PATH)
	uv run pytest --cov=gnlog --cov-report=html

.PHONY: test-watch
test-watch: $(VENV_EDITABLE_PATH)
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
