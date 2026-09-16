# Deployment & Operations Guide

## 1. Local Development
```bash
# 1. Activate venv
.\.venv\Scripts\activate

# 2. Run API
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Run Worker Loop
python -m apps.worker.main

# 4. Run Frontend Dashboard
cd apps/dashboard
npm run dev
```

## 2. Production Docker Deployment
```bash
docker-compose up -d --build
```
This boots:
- `agent_postgres`: PostgreSQL 16 on port 5432
- `agent_redis`: Redis 7 on port 6379
- `agent_api`: FastAPI on port 8000
- `agent_worker`: Background state-machine worker
- `agent_dashboard`: Nginx-served React SPA on port 3000

## 3. Production Health Endpoints
- `GET /health`: Overall system liveness
- `GET /readiness`: Database & Redis pool verification
- `GET /metrics`: Prometheus metrics scraper endpoint
