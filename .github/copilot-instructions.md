# Copilot Instructions for TradingQQuant-Sim

## Project Overview
This is a quant trading research and paper-trading framework built with Python and FastAPI. The application provides simulation utilities for trading strategies including data ingestion, backtesting, and paper trading with Coinbase integration.

## Build Instructions

### Python Environment Setup
```bash
python -m pip install -U pip
pip install -r requirements.txt
```

### Running the Application Locally
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Build
```bash
docker build -t tradingq-app:latest .
docker run -p 8000:8000 tradingq-app:latest
```

### Testing
No test suite is currently configured in the repository. If adding tests, use pytest:
```bash
pip install pytest
pytest
```

### Linting
For JavaScript/Node.js components:
```bash
npm install
npm run lint
```

## Repository Structure
- `main.py` - FastAPI application entry point
- `requirements.txt` - Python dependencies (FastAPI, uvicorn)
- `Dockerfile` - Container configuration using Python 3.11-slim
- `package.json` - Node.js configuration (if needed)
- `.github/workflows/` - CI/CD pipeline for AWS ECR

## Development Guidelines
- The application uses Python 3.11
- FastAPI framework for REST API endpoints
- Docker-based deployment to AWS ECR
- Keep dependencies minimal and up-to-date
- Follow Python PEP 8 style guidelines

## Deployment
The application is automatically built and pushed to AWS ECR on commits to the `main` branch via GitHub Actions workflow.
