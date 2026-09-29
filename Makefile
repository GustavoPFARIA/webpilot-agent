.PHONY: install dev test evals lint fmt types audit check smoke docker

install:        ## Install dependencies and Chromium
	pip install -r requirements-dev.txt
	playwright install chromium

dev:            ## Run the app with auto-reload on http://127.0.0.1:8000
	uvicorn app.main:app --reload

test:           ## Tests with coverage
	pytest -q --cov=app --cov=evals --cov-report=term-missing --cov-fail-under=85

evals:          ## End-to-end agent evals
	python -m evals.run_evals --min-pass-rate 1.0

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check --fix .
	ruff format .

types:
	mypy

audit:          ## Known vulnerabilities in dependencies
	pip-audit -r requirements.txt

check: lint types audit test evals   ## Everything CI runs

smoke:          ## Complete a real task against a running server
	python scripts/smoke_test.py

docker:
	docker build -t webpilot-agent .
