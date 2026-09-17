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
- **Auto-documented API**: FastAPI with automatic OpenAPI/Swagger documentation
- **Free and open**: No accounts, billing, or paywalls — download and run.

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
- SEC API key (from [sec-api.io](https://sec-api.io/)) — only needed for `/analyze/{ticker}`

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
    pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   # Copy .env.example to .env (create .env.example first)
   cp .env.example .env
   ```

    Edit `.env` with your credentials:
    ```env
    SEC_API_KEY=your_sec_api_key_here
    ```

5. **Verify analysis assets**:
   ```bash
   # Checks the LM dictionary and the ONNX model directory
   python scripts/check_assets.py
   ```
   - Dictionary defaults to `data/Loughran-McDonald_MasterDictionary_1993-2024.csv`
     (override with `LM_DICTIONARY_PATH`).
   - Model defaults to `./models/distilfinbert_onnx_q8` (override with
     `MODEL_PATH`). The directory is git-ignored; place the quantized
     `model_quantized.onnx` plus tokenizer files there. Missing assets fail
     with an explicit error — the API never silently reports zero sentiment.

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
├── auth.py               # JWT/API-key verification (persisted store)
├── auth_endpoints.py     # Signup/login/keys with tier enforcement
├── auth_store.py         # File-persisted users and API keys
├── config.py             # Centralized environment configuration
├── benchmark_finbert.py  # Performance testing (MODEL_PATH aware)
├── scripts/
│   └── check_assets.py   # Verify dictionary + model assets
├── data/                 # Loughran-McDonald dictionary + auth store
├── models/               # ONNX ML models (git-ignored, provisioned locally)
├── tests/                # Hermetic pytest suite (no real creds needed)
├── docs/                 # Documentation
├── .env.example          # Environment template (copy to .env)
└── cache_directory/      # Runtime cache (auto-created)
```

## 📊 Performance Characteristics

- **Model Loading**: ~2-3 seconds at startup
- **SEC API Caching**: 1-hour cache TTL for API responses
- **ML Inference**: Optimized with quantized ONNX models
- **Concurrent Requests**: FastAPI async support

## 🔒 Security Considerations

**Current Implementation**:
- Environment-based secret management (see `config.py` + `.env.example`)
- Tiered rate limiting (10/100/1000/10000 per hour) with `X-RateLimit-*` headers
- Input validation (length/content checks, ticker format)
- File-persisted users/API keys with self-selected tiers (local rate-limit labels)

**Production Recommendations**:
- Set a stable `JWT_SECRET_KEY` shared by all workers
- Configure CORS origins and trusted hosts for your domain
- Share `data/`, `cache_directory/`, `models/` across workers
- Add request size limits
- Set up proper logging

## 🚨 Known Limitations

- **Model files are local**: `models/` is git-ignored; provision it per machine
  and verify with `python scripts/check_assets.py`.
- **External keys required**: the `/analyze/{ticker}` flow needs a real
  `SEC_API_KEY`; unit tests run hermetically with mocks (`pytest -m "not integration"`).
- **File-backed state**: users, API keys, and rate buckets persist
  in `data/` + `cache_directory/` — back them up and share them across workers.
- **Tiers are local labels**: signup offers `free`/`basic`/`premium` as
  self-selected rate-limit buckets; there is no billing.

## 📈 Monitoring & Debugging

### Logs
- Application logs: Console output via print statements
- Access logs: FastAPI default logging
- Error tracking: HTTP response codes

### Common Issues

1. **Model Loading Errors**: Ensure `models/` directory has proper files
2. **SEC API Failures**: Check API key validity and rate limits
3. **Cache Permissions**: Ensure write access to `cache_directory/`

## 🤝 Contributing

1. Follow the existing code style (Black formatting)
2. Ensure pre-commit hooks pass
3. Add tests for new functionality (when test framework is implemented)
4. Update documentation for API changes

## 📄 License

[Add your license information here]

## 🔗 Resources

- **SEC API Documentation**: https://sec-api.io/docs
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **DistilFinBERT Model**: https://huggingface.co/ProsusAI/finbert

## 📞 Support

For questions or issues:
1. Check the API documentation at `/docs`
2. Review the brownfield architecture document in `docs/`
3. Submit issues through the repository issue tracker

---

> **Note**: This is a brownfield project. See `docs/brownfield-architecture.md` for detailed technical architecture and development guidelines.