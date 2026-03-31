.PHONY: help setup dev api worker migrate test lint docker-up docker-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Initial project setup
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	playwright install chromium
	cp -n .env.example .env || true
	@echo "✓ Setup complete. Run 'source .venv/bin/activate'"

dev: ## Start all services for local development
	docker compose up -d postgres redis
	@sleep 2
	$(MAKE) migrate
	$(MAKE) api & $(MAKE) worker
	@wait

api: ## Start the API server
	uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload

worker: ## Start Celery worker
	celery -A services.scheduler.celery_app worker --loglevel=info --concurrency=4

beat: ## Start Celery Beat scheduler
	celery -A services.scheduler.celery_app beat --loglevel=info

migrate: ## Run database migrations
	alembic upgrade head

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add users table")
	alembic revision --autogenerate -m "$(MSG)"

test: ## Run tests
	pytest tests/ -v --cov=services --cov=shared --cov-report=term-missing

lint: ## Run linter
	ruff check .
	ruff format --check .

format: ## Auto-format code
	ruff check --fix .
	ruff format .

docker-up: ## Start all services via Docker
	docker compose up -d --build

docker-down: ## Stop all Docker services
	docker compose down

docker-logs: ## Tail Docker logs
	docker compose logs -f

seed: ## Seed database with sample data
	python scripts/seed.py

shell: ## Open Python shell with app context
	python -c "import asyncio; from shared.db.database import get_session; asyncio.run(get_session())"
