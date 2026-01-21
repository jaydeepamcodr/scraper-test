# Manga Scraper

Production-ready, enterprise-grade manga scraping service with Cloudflare bypass capabilities.

## Features

- **Multi-site Support**: mgeko.cc, asuracomic.net, manhwatop.com
- **Cloudflare Bypass**: Using Nodriver browser automation
- **Scalable Architecture**: Celery workers with Redis queue
- **Image Storage**: S3/MinIO compatible storage with WebP optimization
- **REST API**: FastAPI with async support
- **Background Jobs**: Automatic chapter detection and scheduled updates
- **Monitoring**: Flower dashboard for Celery workers

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────┐
│   FastAPI   │────▶│    Redis     │────▶│   Celery Workers    │
│     API     │     │    Queue     │     │  (HTTP + Browser)   │
└─────────────┘     └──────────────┘     └──────────┬──────────┘
                                                    │
                    ┌──────────────┐     ┌──────────▼──────────┐
                    │  PostgreSQL  │◀────│    S3 / MinIO       │
                    │   Database   │     │   Image Storage     │
                    └──────────────┘     └─────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)

### Using Docker (Recommended)

```bash
# Clone and start
git clone <repo>
cd manga-scraper

# Copy environment file
cp .env.example .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Start dependencies (Postgres, Redis, MinIO)
docker-compose up -d postgres redis minio

# Run migrations
alembic upgrade head

# Start API server
uvicorn manga_scraper.api.app:app --reload

# In another terminal, start workers
celery -A manga_scraper.workers.celery_app worker -Q default,scraper,downloader -l INFO

# For browser-based scraping (CF-protected sites)
celery -A manga_scraper.workers.celery_app worker -Q browser -c 2 -l INFO
```

## API Usage

### Add a Series

```bash
curl -X POST http://localhost:8000/api/v1/series/ \
  -H "Content-Type: application/json" \
  -d '{"url": "https://mgeko.cc/manga/some-manga/"}'
```

### List Series

```bash
curl http://localhost:8000/api/v1/series/
```

### Scrape Chapter Images

```bash
curl -X POST http://localhost:8000/api/v1/chapters/1/scrape
```

### Check Job Status

```bash
curl http://localhost:8000/api/v1/jobs/1
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/series/` | GET | List all series |
| `/api/v1/series/` | POST | Add new series by URL |
| `/api/v1/series/{id}` | GET | Get series details |
| `/api/v1/series/{id}/refresh` | POST | Refresh series metadata |
| `/api/v1/chapters/series/{id}` | GET | List chapters |
| `/api/v1/chapters/{id}` | GET | Get chapter with images |
| `/api/v1/chapters/{id}/scrape` | POST | Scrape chapter images |
| `/api/v1/jobs/` | GET | List jobs |
| `/api/v1/jobs/stats` | GET | Job statistics |

## Configuration

See `.env.example` for all configuration options.

Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `S3_ENDPOINT_URL` | S3/MinIO endpoint | `http://localhost:9000` |
| `SCRAPER_CONCURRENT_BROWSERS` | Max browser instances | `3` |
| `RATE_LIMIT_DEFAULT` | Requests per minute | `20` |

## Monitoring

- **API Docs**: http://localhost:8000/docs
- **Flower (Celery)**: http://localhost:5555
- **MinIO Console**: http://localhost:9001

## Supported Sites

| Site | Cloudflare | Method |
|------|------------|--------|
| mgeko.cc | No | HTTP |
| asuracomic.net | Yes | Browser (Nodriver) |
| manhwatop.com | Yes | Browser (Nodriver) |

## Production Deployment

```bash
# Build production images
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build

# Deploy
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Scaling Workers

```bash
# Scale HTTP workers
docker-compose up -d --scale worker-http=4

# Scale browser workers (memory intensive)
docker-compose up -d --scale worker-browser=2
```

## Development

```bash
# Run tests
make test

# Run linter
make lint

# Format code
make format

# Create migration
make migrate-new
```

## License

MIT
