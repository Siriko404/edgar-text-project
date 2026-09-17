# Edgar-Text Deployment Guide

## Overview

This guide covers deployment options for the Edgar-Text API, from local development to production environments.

## Quick Local Setup

### 1. Environment Setup
```bash
# Clone repository
git clone <repository-url>
cd edgar-text

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials:
# - SEC_API_KEY: Get from https://sec-api.io/
# - JWT_SECRET_KEY: Generate with python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Run Application
```bash
# Development server with auto-reload
uvicorn api:app --reload

# Production-like server
uvicorn api:app --host 0.0.0.0 --port 8000
```

### 4. Verify Installation
```bash
# Health check
curl http://localhost:8000/

# API documentation
open http://localhost:8000/docs
```

## Testing

### Run Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_api.py -v

# Run integration tests (requires API keys)
pytest --integration
```

### Code Quality
```bash
# Format code
black .

# Lint code
flake8 .

# Run pre-commit hooks
pre-commit run --all-files
```

## Production Deployment

### Docker Deployment

Create `Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Start application
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  edgar-text:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SEC_API_KEY=${SEC_API_KEY}
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    volumes:
      - ./cache_directory:/app/cache_directory
      - ./models:/app/models
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - edgar-text
    restart: unless-stopped
```

### Cloud Deployment Options

#### Option 1: Heroku
```bash
# Install Heroku CLI and login
heroku create edgar-text-api

# Set environment variables
heroku config:set SEC_API_KEY=your_key
heroku config:set JWT_SECRET_KEY=your_stable_secret

# Create Procfile
echo "web: uvicorn api:app --host 0.0.0.0 --port \$PORT" > Procfile

# Deploy
git push heroku main
```

#### Option 2: AWS Lambda (Serverless)
Create `serverless.yml`:
```yaml
service: edgar-text-api

provider:
  name: aws
  runtime: python3.12
  region: us-east-1
  environment:
    SEC_API_KEY: ${env:SEC_API_KEY}
    JWT_SECRET_KEY: ${env:JWT_SECRET_KEY}

functions:
  api:
    handler: lambda_handler.handler
    events:
      - http:
          path: /{proxy+}
          method: ANY
          cors: true
      - http:
          path: /
          method: ANY
          cors: true

plugins:
  - serverless-python-requirements
```

#### Option 3: DigitalOcean App Platform
Create `.do/app.yaml`:
```yaml
name: edgar-text-api
services:
- name: api
  source_dir: /
  github:
    repo: your-username/edgar-text
    branch: main
  run_command: uvicorn api:app --host 0.0.0.0 --port 8080
  environment_slug: python
  instance_count: 1
  instance_size_slug: basic-xxs
  http_port: 8080
  health_check:
    http_path: /
  envs:
  - key: SEC_API_KEY
    scope: RUN_TIME
    type: SECRET
  - key: JWT_SECRET_KEY
    scope: RUN_TIME
    type: SECRET
```

## Production Configuration

### Environment Variables
```bash
# Required
SEC_API_KEY=your_sec_api_key
JWT_SECRET_KEY=stable_random_secret_shared_by_all_workers

# Optional Security Configuration
CORS_ORIGINS=https://yourfrontend.com,https://www.yourfrontend.com
TRUSTED_HOSTS=yourapi.com,www.yourapi.com
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=3600
ANONYMOUS_RATE_LIMIT=10

# Optional Analysis Assets (defaults shown)
LM_DICTIONARY_PATH=data/Loughran-McDonald_MasterDictionary_1993-2024.csv
MODEL_PATH=./models/distilfinbert_onnx_q8
AUTH_STORE_PATH=data/auth_store.json

# Optional Application Configuration
DEBUG=false
LOG_LEVEL=INFO
```

> Tiers (`free`/`basic`/`premium`) are self-selected at signup and act as
> local rate-limit buckets only. There is no billing; nothing provisions or
> revokes tiers except the account owner editing the auth store.

### Nginx Configuration (nginx.conf)
```nginx
events {
    worker_connections 1024;
}

http {
    upstream edgar_text {
        server edgar-text:8000;
    }

    server {
        listen 80;
        server_name your-domain.com;

        # Security headers
        add_header X-Content-Type-Options nosniff;
        add_header X-Frame-Options DENY;
        add_header X-XSS-Protection "1; mode=block";

        # Rate limiting
        limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

        location / {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://edgar_text;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

## Performance Tuning

### Uvicorn Production Settings
```bash
# Multiple workers for production (--workers cannot be combined with --reload)
uvicorn api:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4
```

> Multi-worker notes: auth users/keys (`data/auth_store.json`) and rate-limit
> buckets are file/disk-cache backed and shared by workers on the same host. All workers must share the same filesystem
> paths (`data/`, `cache_directory/`, `models/`) and the same
> `JWT_SECRET_KEY`; otherwise tokens issued by one worker fail on another.
> Set users back to `free` on upgrade reversal by re-running provisioning.

### Gunicorn Alternative
```bash
# Install gunicorn
pip install gunicorn[uvicorn]

# Run with gunicorn
gunicorn api:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --preload
```

## Monitoring and Logging

### Health Checks
- **Endpoint**: `GET /`
- **Expected Response**: `{"status": "ok", "message": "Edgar-Text API is running"}`
- **Status Code**: 200

### Key Metrics to Monitor
- Response time for `/analyze/{ticker}` endpoints
- Memory usage (ML models are loaded in memory)
- Disk usage (cache directory growth)
- Rate limit hits
- Error rates by endpoint

### Recommended Monitoring Setup
1. **Application Performance**: New Relic, DataDog, or Sentry
2. **Infrastructure**: Prometheus + Grafana
3. **Logs**: ELK Stack or CloudWatch
4. **Uptime**: UptimeRobot or Pingdom

## Security Considerations

### Production Security Checklist
- [ ] Use HTTPS with valid SSL certificates
- [ ] Configure CORS for specific domains only
- [ ] Set up rate limiting (implemented in API)
- [ ] Validate all API inputs (implemented)
- [ ] Set up Web Application Firewall (WAF)
- [ ] Regular security updates
- [ ] Monitor for unusual traffic patterns

### SSL Certificate Setup
```bash
# Using Let's Encrypt with Certbot
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Troubleshooting

### Common Issues

1. **Model Loading Errors**
   ```bash
   # Check if models directory exists and has proper permissions
   ls -la models/
   # Re-download models if needed
   ```

2. **Environment Variable Issues**
   ```bash
   # Verify environment variables are loaded
   printenv | grep -E "SEC_API_KEY|JWT_SECRET_KEY"
   ```

3. **Port Already in Use**
   ```bash
   # Find process using port 8000
   lsof -i :8000
   # Kill process if needed
   kill -9 <PID>
   ```

4. **Permission Denied for Cache Directory**
   ```bash
   # Fix cache directory permissions
   chmod 755 cache_directory/
   chown -R app:app cache_directory/
   ```

### Logs and Debugging
```bash
# View application logs
tail -f /var/log/edgar-text/app.log

# Check system resources
htop
df -h

# Test API endpoints
curl -v http://localhost:8000/
curl -X POST http://localhost:8000/analyze/sentiment \
  -H "Content-Type: application/json" \
  -d '{"text": "test"}'
```

## Backup and Recovery

### Data to Backup
- Environment configuration files
- Cache directory (optional, can be regenerated)
- Application logs
- ML model files (if customized)

### Backup Script Example
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/edgar-text_$DATE"

mkdir -p "$BACKUP_DIR"
cp .env "$BACKUP_DIR/"
cp -r cache_directory "$BACKUP_DIR/" 2>/dev/null || true
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"

echo "Backup created: $BACKUP_DIR.tar.gz"
```

## Support

For deployment issues:
1. Check the GitHub Actions CI/CD logs
2. Review the application logs
3. Verify all environment variables are set correctly
4. Test API endpoints individually
5. Submit issues with full error logs and environment details