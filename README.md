# Edgar-Text: SEC Filing Sentiment Analysis API

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A dual-mode financial text analysis API that combines traditional sentiment analysis (Loughran-McDonald dictionary) with modern ML models (DistilFinBERT) for comprehensive analysis of SEC 10-K filings.

## 🚀 Features

- **Dual Sentiment Analysis**: Traditional financial dictionary + ML-based sentiment scoring
- **SEC Filing Integration**: Professional-grade SEC API integration with intelligent caching
- **Performance Optimized**: Quantized ONNX models for fast CPU inference
- **Readability Metrics**: Gunning Fog scores for document complexity analysis
- **Payment Integration**: Stripe-powered monetization with webhook handling
- **Auto-documented API**: FastAPI with automatic OpenAPI/Swagger documentation

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI Web  │────│  Core Analysis  │────│   SEC API       │
│   Interface     │    │   Engine        │    │   Integration   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐             │
         │              │   ML Models     │             │
         └──────────────│  (ONNX/FinBERT) │─────────────┘
                        └─────────────────┘
                                 │
                        ┌─────────────────┐
                        │  DiskCache +    │
                        │  L-M Dictionary │
                        └─────────────────┘
```

## 📋 Quick Start

### Prerequisites

- Python 3.12 or higher
- SEC API key (from [sec-api.io](https://sec-api.io/))
- Stripe account (for payment features)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd edgar-text
   ```

2. **Set up virtual environment**:
   ```bash
   python -m venv .venv

   # On Windows
   .venv\Scripts\activate

   # On macOS/Linux
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   # Core dependencies
   pip install fastapi uvicorn[standard]
   pip install stripe python-dotenv
   pip install sec-api diskcache textstat
   pip install optimum[onnxruntime] transformers

   # Development dependencies
   pip install black flake8 pre-commit
   ```

4. **Configure environment variables**:
   ```bash
   # Copy .env.example to .env (create .env.example first)
   cp .env.example .env
   ```

   Edit `.env` with your credentials:
   ```env
   SEC_API_KEY=your_sec_api_key_here
   STRIPE_SECRET_KEY=sk_test_your_stripe_test_key
   STRIPE_PRICE_ID=price_your_stripe_price_id
   STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
   ```

5. **Download ML models**:
   ```bash
   # Models are auto-downloaded on first run
   # Ensure models/ directory has proper permissions
   ```

### Running the Application

**Start the API server**:
```bash
uvicorn api:app --reload
```

**Access the application**:
- API server: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- ReDoc documentation: http://localhost:8000/redoc

## 🔍 API Usage

### Analyze Company Filing

Perform comprehensive analysis of a company's latest 10-K filings:

```bash
curl "http://localhost:8000/analyze/AAPL"
```

**Response**:
```json
{
  "ticker": "AAPL",
  "latest_filing": {
    "filed_at": "2024-10-31T00:00:00",
    "link": "https://www.sec.gov/Archives/edgar/data/...",
    "gunning_fog_score": 14.2,
    "sentiment": {"positive_count": 45, "negative_count": 23}
  },
  "prior_filing": {
    "filed_at": "2023-10-27T00:00:00",
    "link": "https://www.sec.gov/Archives/edgar/data/...",
    "gunning_fog_score": 13.8,
    "sentiment": {"positive_count": 38, "negative_count": 31}
  },
  "comparison_metrics": {
    "change_score_similarity_ratio": 0.8542
  }
}
```

### ML-Based Sentiment Analysis

Analyze any text with the DistilFinBERT model:

```bash
curl -X POST "http://localhost:8000/analyze/sentiment" \
  -H "Content-Type: application/json" \
  -d '{"text": "The company reported strong quarterly results."}'
```

**Response**:
```json
{
  "label": "POSITIVE",
  "score": 0.8934
}
```

### Health Check

```bash
curl "http://localhost:8000/"
```

## 🧪 Development

### Code Quality

The project uses pre-commit hooks for code quality:

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files

# Individual tools
black .                    # Format code
flake8 .                  # Lint code
```

### Performance Testing

Benchmark the ML model performance:

```bash
python benchmark_finbert.py
```

### Project Structure

```
edgar-text/
├── api.py                 # FastAPI web service
├── main.py               # Core analysis engine
├── benchmark_finbert.py  # Performance testing
├── data/                 # Loughran-McDonald dictionary
├── models/               # ONNX ML models
├── docs/                 # Documentation
├── .env                  # Environment configuration
└── cache_directory/      # Runtime cache (auto-created)
```

## 📊 Performance Characteristics

- **Model Loading**: ~2-3 seconds at startup
- **SEC API Caching**: 1-hour cache TTL for API responses
- **ML Inference**: Optimized with quantized ONNX models
- **Concurrent Requests**: FastAPI async support

## 🔒 Security Considerations

**Current Implementation**:
- Environment-based secret management
- Stripe webhook signature verification
- Basic error handling

**Production Recommendations**:
- Add rate limiting
- Implement input validation
- Configure CORS policies
- Add request size limits
- Set up proper logging

## 🚨 Known Limitations

- **No Test Suite**: Testing infrastructure needs implementation
- **Manual Deployment**: No CI/CD pipeline configured
- **Limited Error Handling**: Basic error responses
- **No Authentication**: Open API endpoints (implement as needed)

## 📈 Monitoring & Debugging

### Logs
- Application logs: Console output via print statements
- Access logs: FastAPI default logging
- Error tracking: HTTP response codes

### Common Issues

1. **Model Loading Errors**: Ensure `models/` directory has proper files
2. **SEC API Failures**: Check API key validity and rate limits
3. **Stripe Webhooks**: Verify webhook secret configuration
4. **Cache Permissions**: Ensure write access to `cache_directory/`

## 🤝 Contributing

1. Follow the existing code style (Black formatting)
2. Ensure pre-commit hooks pass
3. Add tests for new functionality (when test framework is implemented)
4. Update documentation for API changes

## 📄 License

[Add your license information here]

## 🔗 Resources

- **SEC API Documentation**: https://sec-api.io/docs
- **Stripe API Documentation**: https://stripe.com/docs/api
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **DistilFinBERT Model**: https://huggingface.co/ProsusAI/finbert

## 📞 Support

For questions or issues:
1. Check the API documentation at `/docs`
2. Review the brownfield architecture document in `docs/`
3. Submit issues through the repository issue tracker

---

> **Note**: This is a brownfield project. See `docs/brownfield-architecture.md` for detailed technical architecture and development guidelines.