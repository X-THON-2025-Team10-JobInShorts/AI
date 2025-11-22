# AI Video Processing Pod - Makefile

.PHONY: help install test test-unit test-integration test-coverage lint format docker-build docker-run clean

# Default target
help:
	@echo "🎬 AI Video Processing Pod - Available Commands:"
	@echo ""
	@echo "📦 Setup & Dependencies:"
	@echo "  make install          - Install Python dependencies"
	@echo "  make install-dev      - Install development dependencies"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test            - Run all tests"
	@echo "  make test-unit       - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-coverage   - Run tests with coverage report"
	@echo "  make test-watch      - Run tests in watch mode"
	@echo ""
	@echo "🔍 Code Quality:"
	@echo "  make lint            - Run linting checks"
	@echo "  make format          - Format code"
	@echo "  make type-check      - Run type checking"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  make docker-build    - Build Docker image"
	@echo "  make docker-run      - Run Docker container"
	@echo "  make docker-test     - Run tests in Docker"
	@echo ""
	@echo "🧹 Cleanup:"
	@echo "  make clean           - Clean temporary files"
	@echo "  make clean-docker    - Clean Docker images"

# Python virtual environment
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Setup virtual environment
$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

# Install dependencies
install: $(VENV)/bin/activate
	$(PIP) install -r requirements.txt

install-dev: install
	$(PIP) install pytest pytest-asyncio pytest-mock pytest-cov black isort flake8 mypy

# Testing
test: install-dev
	@echo "🧪 Running all tests..."
	$(VENV)/bin/pytest tests/ -v

test-unit: install-dev
	@echo "🧪 Running unit tests..."
	$(VENV)/bin/pytest tests/ -v -m "unit or not integration"

test-integration: install-dev
	@echo "🧪 Running integration tests..."
	$(VENV)/bin/pytest tests/ -v -m "integration"

test-coverage: install-dev
	@echo "📊 Running tests with coverage..."
	$(VENV)/bin/pytest tests/ --cov=src --cov-report=html --cov-report=term-missing --cov-fail-under=80

test-watch: install-dev
	@echo "👀 Running tests in watch mode..."
	$(VENV)/bin/pytest-watch tests/

# Code quality
lint: install-dev
	@echo "🔍 Running linting checks..."
	$(VENV)/bin/flake8 src/ tests/ --max-line-length=100 --ignore=E203,W503
	$(VENV)/bin/isort --check-only src/ tests/

format: install-dev
	@echo "✨ Formatting code..."
	$(VENV)/bin/black src/ tests/ --line-length=100
	$(VENV)/bin/isort src/ tests/

type-check: install-dev
	@echo "🔍 Running type checks..."
	$(VENV)/bin/mypy src/ --ignore-missing-imports

# Docker
docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t ai-video-processor .

docker-run: docker-build
	@echo "🚀 Running Docker container..."
	docker run --env-file .env.example ai-video-processor

docker-test: docker-build
	@echo "🧪 Running tests in Docker..."
	docker run --rm -v $(PWD):/app -w /app ai-video-processor pytest tests/ -v

docker-shell:
	@echo "🐚 Opening Docker shell..."
	docker run --rm -it -v $(PWD):/app -w /app ai-video-processor /bin/bash

# Development helpers
dev-setup: install-dev
	@echo "⚙️ Setting up development environment..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "📝 Created .env file from .env.example"; \
		echo "🔑 Please update .env with your actual API keys"; \
	fi

run-local: install
	@echo "🏃 Running locally..."
	$(PYTHON) -m src.main

# Cleanup
clean:
	@echo "🧹 Cleaning temporary files..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf htmlcov/
	rm -rf .coverage

clean-docker:
	@echo "🐳 Cleaning Docker images..."
	docker rmi ai-video-processor 2>/dev/null || true
	docker image prune -f

clean-all: clean clean-docker
	rm -rf $(VENV)

# CI/CD helpers
ci-test: install-dev
	@echo "🚀 Running CI tests..."
	$(VENV)/bin/pytest tests/ --junitxml=test-results.xml --cov=src --cov-report=xml

pre-commit: format lint type-check test
	@echo "✅ Pre-commit checks completed successfully!"

# Documentation
docs-serve:
	@echo "📚 Serving documentation..."
	@echo "README.md available at: file://$(PWD)/README.md"
	
# Quick development commands
dev: dev-setup
	@echo "🎯 Quick development setup completed!"
	@echo "📝 Next steps:"
	@echo "  1. Update .env with your API keys"
	@echo "  2. Run 'make test' to verify setup"
	@echo "  3. Run 'make run-local' to start the application"

# Health check
health:
	@echo "🩺 Health check..."
	@echo "Python version: $$(python3 --version)"
	@echo "Docker version: $$(docker --version 2>/dev/null || echo 'Docker not installed')"
	@echo "Git status: $$(git status --porcelain | wc -l) uncommitted files"
	@if [ -f .env ]; then echo "✅ .env file exists"; else echo "❌ .env file missing"; fi
	@if [ -d $(VENV) ]; then echo "✅ Virtual environment exists"; else echo "❌ Virtual environment missing"; fi