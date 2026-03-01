.PHONY: setup venv install install-dev install-ui install-all clean build-web build build-api

venv:
	uv venv

install: venv
	VIRTUAL_ENV="$$(pwd)/.venv" uv pip install -e .

install-dev: venv
	VIRTUAL_ENV="$$(pwd)/.venv" uv pip install -e ".[all,dev]"

install-ui:
	npm --prefix web install

install-all: install-dev install-ui

setup: install-all

clean:
	rm -rf .venv
	rm -rf web/node_modules
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +

build-web:
	cd web && npm run build
	rm -rf src/agent_os/web_static
	cp -r web/dist src/agent_os/web_static

build: build-web
	uv build --wheel

build-api:
	uv build --wheel
