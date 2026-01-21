.PHONY: help install dev test lint format clean docker-up docker-down docker-logs migrate shell

# Default target
help:
	@echo "Manga Scraper - Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  make install     - Install dependencies"
	@echo "  make dev         - Run development server"
	@echo "  make test        - Run tests"
	@echo "  make lint        - Run linter"
	@echo "  make format      - Format code"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up   - Start all services"
	@echo "  make docker-down - Stop all services"
	@echo "  make docker-logs - View logs"
	@echo "  make docker-build - Rebuild containers"
	@echo ""
	@echo "Database:"
	@echo "  make migrate     - Run database migrations"
	@echo "  make migrate-new - Create new migration"
	@echo ""
	@echo "Utilities:"
	@echo "  make shell       - Open Python shell"
	@echo "  make clean       - Clean cache files"

# Development
install:
	pip install -e ".[dev]"

dev:
	uvicorn manga_scraper.api.app:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --cov=manga_scraper --cov-report=term-missing

lint:
	ruff check manga_scraper tests
	mypy manga_scraper

format:
	ruff format manga_scraper tests
	ruff check --fix manga_scraper tests

# Docker commands
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-build:
	docker-compose build --no-cache

docker-restart:
	docker-compose restart

docker-ps:
	docker-compose ps

# Database
migrate:
	alembic upgrade head

migrate-new:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

migrate-down:
	alembic downgrade -1

# Workers
worker:
	celery -A manga_scraper.workers.celery_app worker -Q default,scraper,downloader -l INFO

worker-browser:
	celery -A manga_scraper.workers.celery_app worker -Q browser -c 2 -l INFO

beat:
	celery -A manga_scraper.workers.celery_app beat -l INFO

flower:
	celery -A manga_scraper.workers.celery_app flower --port=5555

# Utilities
shell:
	python -c "from manga_scraper.models import *; from manga_scraper.config import settings; import asyncio" -i

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Production
prod-up:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-down:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

prod-logs:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
