# Edgar-Text API Documentation

## Overview

The Edgar-Text API provides comprehensive sentiment analysis and textual metrics for SEC 10-K filings. It combines traditional financial sentiment analysis (Loughran-McDonald dictionary) with modern ML-based sentiment scoring using DistilFinBERT.

**Base URL:** `https://your-domain.com/api` (Production) or `http://localhost:8000` (Development)

**API Version:** 1.0.0

## Authentication

Edgar-Text API supports two authentication methods:

### 1. API Keys (Recommended for Applications)

Include your API key in the Authorization header:

```http
Authorization: Bearer edgar_your_api_key_here
```

### 2. JWT Tokens (For User Sessions)

Include your JWT token in the Authorization header:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Getting Started

1. **Sign up for an account**: `POST /auth/signup`
2. **Generate an API key**: `POST /auth/api-key`
3. **Start making requests** with your API key

## Rate Limiting

Rate limits vary by authentication tier:

| Tier | Rate Limit | Authentication Required |
|------|------------|------------------------|
| Anonymous | 10 requests/hour | No |
| Free | 100 requests/hour | Yes |
| Basic | 1,000 requests/hour | Yes |
| Premium | 10,000 requests/hour | Yes |

Rate limit headers are included in rate-limited responses
(analysis and authentication endpoints):
- `X-RateLimit-Limit`: Maximum requests per window
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Unix timestamp when the window resets

## Endpoints

### Health & Status

#### `GET /`
Check API health and status.

**Response:**
```json
{
  "status": "ok",
  "message": "Edgar-Text API is running"
}
```

#### `GET /ready`
Readiness probe for orchestration and deploy scripts (liveness stays on `GET /`).

**Response:**
```json
{
  "ready": true,
  "checks": {
    "sec_api_key": true,
    "dictionary": true,
    "model": true,
    "auth_store": true
  }
}
```

#### `GET /metrics`
Get application performance metrics (monitoring endpoint).

**Response:**
```json
{
  "timestamp": "2025-01-01T12:00:00Z",
  "counters": {
    "health_check_requests": 150,
    "sentiment_analysis_success": 45
  },
  "gauges": {
    "system_cpu_percent": 25.3,
    "system_memory_percent": 68.1
  }
}
```

### Authentication Endpoints

#### `POST /auth/signup`
Create a new user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "secure_password",
  "tier": "free"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user_id": "user_123",
  "tier": "free"
}
```

#### `POST /auth/login`
Authenticate with existing credentials.

**Request Body:**
```json
{
  "email": "you@example.com",
  "password": "your-password"
}
```

Passwords are at least 8 characters. A `demo@example.com` account exists only when the server runs with `ENABLE_DEMO_ACCOUNT=1`; never enable it on a reachable server.

**Response:** Same as signup

#### `POST /auth/api-key`
Generate a new API key (requires authentication).

**Headers:**
```http
Authorization: Bearer your_jwt_token
```

**Request Body:**
```json
{
  "name": "My Application Key",
  "tier": "basic"
}
```

**Response:**
```json
{
  "api_key": "edgar_abc123def456...",
  "key_id": "abc123de",
  "tier": "basic",
  "rate_limit": 1000,
  "created_at": "2025-01-01T12:00:00Z"
}
```

#### `GET /auth/me`
Get current user information (requires authentication).

**Response:**
```json
{
  "user_id": "user_123",
  "email": "user@example.com",
  "tier": "basic",
  "rate_limit": 1000,
  "auth_type": "api_key"
}
```

### Analysis Endpoints

#### `POST /analyze/sentiment`
Analyze sentiment of any text using DistilFinBERT.

**Headers:**
```http
Authorization: Bearer your_api_key  # Optional but increases rate limit
Content-Type: application/json
```

**Request Body:**
```json
{
  "text": "The company reported strong quarterly results with increased revenue and profitability."
}
```

**Validation Rules:**
- `text`: 1-5000 characters, required
- No malicious content (script tags, javascript:, data: URLs)

**Response:**
```json
{
  "label": "POSITIVE",
  "score": 0.8934
}
```

**Possible Labels:**
- `POSITIVE`: Positive sentiment (score 0.0-1.0)
- `NEGATIVE`: Negative sentiment (score 0.0-1.0)
- `NEUTRAL`: Neutral sentiment (score 0.0-1.0)

#### `GET /analyze/{ticker}`
Comprehensive analysis of SEC 10-K filings for a company.

**Parameters:**
- `ticker` (path): Stock ticker symbol (1-5 uppercase letters, e.g., "AAPL", "MSFT")

**Headers:**
```http
Authorization: Bearer your_api_key  # Optional but increases rate limit
```

**Example Request:**
```http
GET /analyze/AAPL
Authorization: Bearer edgar_abc123def456...
```

**Response:**
```json
{
  "ticker": "AAPL",
  "latest_filing": {
    "filed_at": "2024-10-31T00:00:00",
    "link": "https://www.sec.gov/Archives/edgar/data/...",
    "gunning_fog_score": 14.2,
    "sentiment": {
      "positive_count": 45,
      "negative_count": 23
    }
  },
  "prior_filing": {
    "filed_at": "2023-10-27T00:00:00",
    "link": "https://www.sec.gov/Archives/edgar/data/...",
    "gunning_fog_score": 13.8,
    "sentiment": {
      "positive_count": 38,
      "negative_count": 31
    }
  },
  "comparison_metrics": {
    "change_score_similarity_ratio": 0.8542
  }
}
```

**Metrics Explained:**
- `gunning_fog_score`: Readability metric (higher = more complex)
- `sentiment.positive_count`: Number of positive words (Loughran-McDonald dictionary)
- `sentiment.negative_count`: Number of negative words (Loughran-McDonald dictionary)
- `change_score_similarity_ratio`: Text similarity between filings (0.0-1.0, higher = more similar)

### Payments

None. This is a free tool with no billing, checkout, or webhook endpoints.
Tiers (`free`/`basic`/`premium`) are self-selected at signup and act as local
rate-limit buckets only.

## Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Error description"
}
```

### Common HTTP Status Codes

| Status Code | Description | Example |
|-------------|-------------|---------|
| 400 | Bad Request | Invalid ticker format |
| 401 | Unauthorized | Invalid or missing API key |
| 403 | Forbidden | Insufficient tier access |
| 404 | Not Found | Company ticker not found |
| 422 | Validation Error | Invalid request data |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server-side error |
| 502 | Bad Gateway | SEC extraction failed |
| 503 | Service Unavailable | Model not loaded |

### Error Examples

**Invalid Ticker Format:**
```json
{
  "detail": "Invalid ticker format. Must be 1-5 uppercase letters."
}
```

**Rate Limit Exceeded:**
```json
{
  "detail": "Rate limit exceeded. Please try again later."
}
```

**Authentication Required:**
```json
{
  "detail": "Authentication required"
}
```

**Validation Error:**
```json
{
  "detail": [
    {
      "loc": ["body", "text"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

## SDK Examples

### Python

```python
import requests

class EdgarTextClient:
    def __init__(self, api_key, base_url="https://api.edgar-text.com"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def analyze_sentiment(self, text):
        response = requests.post(
            f"{self.base_url}/analyze/sentiment",
            headers=self.headers,
            json={"text": text}
        )
        response.raise_for_status()
        return response.json()

    def analyze_company(self, ticker):
        response = requests.get(
            f"{self.base_url}/analyze/{ticker}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

# Usage
client = EdgarTextClient("edgar_your_api_key_here")

# Analyze sentiment
result = client.analyze_sentiment("The company shows strong growth potential.")
print(f"Sentiment: {result['label']} (confidence: {result['score']:.2f})")

# Analyze company
analysis = client.analyze_company("AAPL")
print(f"Latest filing sentiment: {analysis['latest_filing']['sentiment']}")
```

### JavaScript/Node.js

```javascript
class EdgarTextClient {
    constructor(apiKey, baseUrl = 'https://api.edgar-text.com') {
        this.apiKey = apiKey;
        this.baseUrl = baseUrl;
        this.headers = {
            'Authorization': `Bearer ${apiKey}`,
            'Content-Type': 'application/json'
        };
    }

    async analyzeSentiment(text) {
        const response = await fetch(`${this.baseUrl}/analyze/sentiment`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({ text })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        }

        return response.json();
    }

    async analyzeCompany(ticker) {
        const response = await fetch(`${this.baseUrl}/analyze/${ticker}`, {
            headers: this.headers
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        }

        return response.json();
    }
}

// Usage
const client = new EdgarTextClient('edgar_your_api_key_here');

// Analyze sentiment
client.analyzeSentiment('The company shows strong growth potential.')
    .then(result => {
        console.log(`Sentiment: ${result.label} (confidence: ${result.score.toFixed(2)})`);
    })
    .catch(console.error);

// Analyze company
client.analyzeCompany('AAPL')
    .then(analysis => {
        console.log('Latest filing sentiment:', analysis.latest_filing.sentiment);
    })
    .catch(console.error);
```

### cURL Examples

**Analyze Sentiment:**
```bash
curl -X POST "https://api.edgar-text.com/analyze/sentiment" \
  -H "Authorization: Bearer edgar_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{"text": "The company reported excellent quarterly results."}'
```

**Analyze Company:**
```bash
curl "https://api.edgar-text.com/analyze/AAPL" \
  -H "Authorization: Bearer edgar_your_api_key_here"
```

**Check Readiness:**
```bash
curl "http://localhost:8000/ready"
```

## Interactive Documentation

When running the API server, interactive documentation is available at:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

These interfaces allow you to:
- Explore all endpoints
- Test API calls directly in the browser
- View request/response schemas
- See authentication requirements

## Best Practices

### Authentication
1. **Use API Keys for Applications**: More stable than JWT tokens
2. **Secure Storage**: Never commit API keys to version control
3. **Rotate Keys Regularly**: Generate new keys and revoke old ones
4. **Use Environment Variables**: Store keys in `.env` files or environment variables

### Rate Limiting
1. **Implement Backoff**: Use exponential backoff when hitting rate limits
2. **Cache Results**: Cache analysis results to reduce API calls
3. **Batch Requests**: Analyze multiple texts in sequence rather than parallel
4. **Monitor Usage**: Track your API usage against your tier limits

### Error Handling
1. **Handle All Status Codes**: Implement proper error handling for all possible responses
2. **Retry Logic**: Implement retry logic for 5xx errors with backoff
3. **Validate Input**: Validate data before sending to reduce 4xx errors
4. **Log Errors**: Log API errors for debugging and monitoring

### Performance
1. **Use Appropriate Tiers**: Upgrade to higher tiers for better rate limits
2. **Optimize Text Length**: Shorter texts process faster
3. **Connection Pooling**: Reuse HTTP connections for better performance
4. **Async/Parallel**: Use async operations where supported

## Support

- **API Documentation**: This document and interactive docs at `/docs`
- **GitHub Issues**: Report bugs and request features
- **Email Support**: Available for Premium tier users
- **Status Page**: Check API status and incidents

## Changelog

### Version 1.0.0 (Current)
- Initial release with sentiment analysis and company filing analysis
- JWT and API key authentication
- Rate limiting and monitoring
- Comprehensive error handling
- Interactive API documentation