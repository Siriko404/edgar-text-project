# Edgar-Text Brownfield Architecture Document

## Introduction

This document captures the CURRENT STATE of the Edgar-Text codebase, including technical debt, workarounds, and real-world patterns. It serves as a reference for AI agents working on enhancements to this financial text analysis API.

**Project Purpose:** SEC filing sentiment analysis API that combines traditional financial dictionaries (Loughran-McDonald) with modern ML models (DistilFinBERT) for comprehensive textual analysis of corporate 10-K filings.

### Document Scope

Comprehensive documentation of entire system - no PRD provided.

### September 2026 Refresh (supersedes stale claims below)

Since v1.0, the gaps listed under Technical Debt / Testing / Security were
closed: Pydantic v2 compatibility (`pattern`, `field_validator`); centralized
`config.py` + full `.env.example`; configurable `LM_DICTIONARY_PATH` /
`MODEL_PATH` with explicit missing-asset errors and `scripts/check_assets.py`;
hermetic pytest suite (`tests/`, `--integration` opt-in); tiered
rate limits with `X-RateLimit-*` headers; file-persisted users/API keys
(`auth_store.py`); env-driven CORS/trusted-hosts/limits and corrected
multi-worker deployment docs. Where sections below still say these are
missing, treat this note as authoritative.

Billing was then removed entirely: the project ships as a free downloadable
tool, so Stripe checkout/webhook code, `STRIPE_*` configuration,
`success.html`/`cancel.html`, and payment tests were deleted. Tiers remain
only as self-selected local rate-limit labels. Where sections below describe
payment processing or monetization, they are historical.

Ship-hardening followed: dotenv loads before auth so `.env` secrets apply;
rate limiting is enforced from one shared module on analysis and auth
endpoints with disk-cache-shared buckets; API keys persist as SHA-256
lookups (plaintext shown once, never stored); key revocation is owner-only;
the `/auth/demo-keys` endpoint was deleted; the auth store serializes writers
with file locks and quarantines corrupt files instead of resetting silently;
company-analysis failures return typed HTTP codes (404/500/502); and a
`/ready` probe reports sec-key, dictionary, model, and store state.

### Change Log

| Date       | Version | Description                 | Author         |
| ---------- | ------- | --------------------------- | -------------- |
| 2025-09-17 | 1.0     | Initial brownfield analysis | Winston (Architect) |

## Quick Reference - Key Files and Entry Points

### Critical Files for Understanding the System

- **Main Entry**: `main.py` - Core business logic and SEC filing analysis
- **API Interface**: `api.py` - FastAPI web service with ML model integration
- **Performance Testing**: `benchmark_finbert.py` - ONNX model benchmarking
- **Configuration**: `.env` - Environment variables (API keys, Stripe config)
- **Data Assets**: `data/Loughran-McDonald_MasterDictionary_1993-2024.csv` - Financial sentiment dictionary
- **ML Models**: `models/distilfinbert_onnx_q8/` - Quantized ONNX sentiment model

### Key Integration Points

- **SEC API**: Professional-grade ExtractorApi for 10-K filing extraction
- **Stripe Payments**: Checkout and webhook processing for monetization
- **ONNX Runtime**: Optimized ML inference for sentiment analysis
- **DiskCache**: Persistent caching for API responses

## High Level Architecture

### Technical Summary

**Edgar-Text** is a dual-mode financial text analysis system that provides both traditional sentiment analysis (Loughran-McDonald dictionary) and modern ML-based sentiment analysis (DistilFinBERT) for SEC 10-K filings. The system is built as a FastAPI service with integrated payment processing for commercialization.

### Actual Tech Stack

| Category        | Technology      | Version/Notes                           |
| --------------- | --------------- | --------------------------------------- |
| Runtime         | Python          | 3.12+ (from .venv structure)           |
| Web Framework   | FastAPI         | Latest (auto-generates OpenAPI docs)   |
| ML Runtime      | ONNX Runtime    | Optimized CPU inference                 |
| ML Models       | DistilFinBERT   | Quantized (Q8) for performance         |
| Caching         | DiskCache       | Persistent file-based cache            |
| Payments        | Stripe          | Test mode integration                   |
| External APIs   | SEC API         | Professional ExtractorApi + QueryApi   |
| Text Analysis   | TextStat        | Readability metrics (Gunning Fog)      |
| Code Quality    | Black + Flake8  | Pre-commit hooks configured             |

### Repository Structure Reality Check

- **Type**: Simple Python package (not a framework-heavy project)
- **Package Manager**: pip with virtual environment
- **Notable**: Minimal dependencies, focused on core functionality

## Source Tree and Module Organization

### Project Structure (Actual)

```text
edgar-text/
├── .bmad-core/          # BMad framework (AI agent system)
├── .claude/             # Claude AI configuration
├── .gemini/             # Gemini AI configuration
├── .qwen/               # Qwen AI configuration
├── .github/             # GitHub workflows (empty)
├── .venv/               # Python virtual environment
├── __pycache__/         # Python bytecode cache
├── cache_directory/     # DiskCache storage (runtime generated)
├── data/
│   └── Loughran-McDonald_MasterDictionary_1993-2024.csv  # 9MB sentiment dictionary
├── docs/
│   ├── BENCHMARK.md     # Performance documentation
│   └── qa/              # Quality assurance reports
├── models/
│   ├── distilfinbert_onnx/     # Original ONNX model
│   └── distilfinbert_onnx_q8/  # Quantized version (used in production)
├── main.py              # Core analysis engine (134 lines)
├── api.py               # FastAPI web service (196 lines)
├── benchmark_finbert.py # Performance testing (30 lines)
├── .env                 # Environment variables (API keys)
├── .flake8              # Linting configuration
├── .gitignore           # Git ignore patterns
├── .pre-commit-config.yaml  # Code quality hooks
├── README.md            # Minimal (15 bytes - NEEDS EXPANSION)
├── success.html         # Stripe success page (3 bytes)
└── cancel.html          # Stripe cancel page (3 bytes)
```

### Key Modules and Their Purpose

- **Main Analysis Engine**: `main.py` - SEC filing extraction, sentiment analysis, readability metrics
- **Web API Interface**: `api.py` - FastAPI service with ML model endpoints and payment processing
- **Performance Testing**: `benchmark_finbert.py` - ONNX model latency benchmarking
- **Financial Dictionary**: Uses cached Loughran-McDonald academic word lists for traditional sentiment analysis

## Data Models and APIs

### Core Data Structures

**Primary Data Models** (inferred from code analysis):

1. **Analysis Result** (from `main.py:analyze_company()`):
```python
{
    "ticker": str,
    "latest_filing": {
        "filed_at": datetime,
        "link": str,
        "gunning_fog_score": float,
        "sentiment": {"positive_count": int, "negative_count": int}
    },
    "prior_filing": {
        "filed_at": datetime,
        "link": str,
        "gunning_fog_score": float,
        "sentiment": {"positive_count": int, "negative_count": int}
    },
    "comparison_metrics": {
        "change_score_similarity_ratio": float
    }
}
```

2. **Sentiment Analysis** (from `api.py`):
```python
# Request
{"text": str}

# Response
{"label": str, "score": float}  # label: POSITIVE/NEGATIVE/NEUTRAL
```

### API Specifications

**Available Endpoints:**

- `GET /` - Health check
- `GET /analyze/{ticker}` - Full SEC filing analysis
- `POST /analyze/sentiment` - ML-based sentiment analysis
- `POST /create-checkout-session` - Stripe payment initiation
- `POST /webhook` - Stripe webhook handler

**OpenAPI Documentation**: Auto-generated at `/docs` when running FastAPI (not documented separately)

## Technical Debt and Known Issues

### Critical Technical Debt

1. **No Test Suite**: Complete absence of testing infrastructure
   - **Risk**: High regression potential, no validation of core functionality
   - **Impact**: Cannot safely refactor or add features

2. **Minimal Documentation**: README is 15 bytes, no API documentation
   - **Risk**: Knowledge transfer impossible, poor developer experience
   - **Impact**: Onboarding friction, maintenance burden

3. **Security Gaps**: No input validation, rate limiting, or API key validation
   - **Risk**: API abuse, potential security vulnerabilities
   - **Impact**: Production deployment risks

4. **Hard-coded Paths**: Model paths and file paths not configurable
   - **File**: `api.py:48` - `"./models/distilfinbert_onnx_q8"`
   - **File**: `main.py:28` - `"data/Loughran-McDonald_MasterDictionary_1993-2024.csv"`
   - **Impact**: Deployment flexibility issues

### Workarounds and Gotchas

- **Model Loading**: Global variable pattern in `api.py:38` - acceptable for single-instance deployment
- **Environment Loading**: Must call `load_dotenv()` before importing `main.py` (see `api.py:12-16`)
- **Cache Directory**: Auto-created by DiskCache, ensure write permissions in deployment
- **Stripe Webhooks**: Uses in-memory event store for idempotency (line 69) - will reset on restart

### Medium Priority Technical Debt

1. **No Dependency Management**: Missing `requirements.txt` or `pyproject.toml`
2. **No Error Monitoring**: Print statements for logging, no structured logging
3. **Payment Logic**: TODO comment at line 189 in webhook handler
4. **Model Versioning**: No model version tracking or update mechanism

## Integration Points and External Dependencies

### External Services

| Service | Purpose | Integration Type | Key Files | Configuration |
|---------|---------|------------------|-----------|---------------|
| SEC API | 10-K filing extraction | REST API + Python SDK | `main.py:14-15` | `SEC_API_KEY` in .env |
| Stripe | Payment processing | REST API + Python SDK | `api.py:20-28` | Multiple Stripe keys in .env |
| Hugging Face | ML model hosting | Direct model download | `api.py:48-50` | No auth required |

### Internal Integration Points

- **API-Core Integration**: `api.py` imports and calls `main.analyze_company()`
- **Model Loading**: FastAPI startup event loads ONNX model into memory
- **Caching Layer**: DiskCache provides transparent caching for SEC API calls
- **Payment Flow**: Stripe checkout → webhook → (TODO: user provisioning)

### API Dependencies

**Python Packages** (inferred from imports):
- `fastapi` - Web framework
- `stripe` - Payment processing
- `sec_api` - SEC filing access
- `optimum[onnxruntime]` - ML model optimization
- `transformers` - Tokenizer for ML models
- `diskcache` - Persistent caching
- `textstat` - Text readability metrics
- `python-dotenv` - Environment variable management
- `pydantic` - Data validation (via FastAPI)

## Development and Deployment

### Local Development Setup

**Current Working Steps:**

1. **Environment Setup**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install [dependencies]  # NO requirements.txt - manual installation needed
   ```

2. **Configuration**:
   - Copy `.env` template and fill in API keys
   - Ensure `data/Loughran-McDonald_MasterDictionary_1993-2024.csv` exists
   - Ensure `models/distilfinbert_onnx_q8/` contains model files

3. **Running**:
   ```bash
   uvicorn api:app --reload  # Starts FastAPI server on port 8000
   python main.py            # Direct CLI usage (not web API)
   python benchmark_finbert.py  # Performance testing
   ```

### Known Development Issues

- **Missing Dependencies**: No `requirements.txt` - must manually install packages
- **Model Files**: Large model files not in git - need separate download/setup
- **API Keys**: Test keys committed to `.env` (development only)

### Build and Deployment Process

**Current State**: No formal build or deployment process

**Manual Deployment Requirements**:
- Python 3.12+ environment
- All dependencies installed
- Model files properly placed
- Environment variables configured
- Write permissions for cache directory

## Testing Reality

### Current Test Coverage

- **Unit Tests**: 0% - No test files exist
- **Integration Tests**: 0% - No test framework
- **E2E Tests**: 0% - No test automation
- **Manual Testing**: Likely primary QA method

### Missing Test Infrastructure

- No `pytest` or testing framework
- No test configuration files
- No CI/CD testing pipeline
- No coverage measurement tools
- No test data fixtures

### Testing Recommendations

**Critical Test Areas** (when implementing):
1. SEC API integration and caching
2. ML model inference accuracy
3. Payment webhook handling
4. Error scenarios and edge cases
5. Performance under load

## Performance Characteristics

### Known Performance Data

**From `benchmark_finbert.py`:**
- ONNX model optimized for CPU inference
- Quantized (Q8) for reduced memory and faster inference
- Benchmark suggests focus on latency optimization

**Caching Strategy:**
- SEC API calls cached with DiskCache (1-hour expiry)
- Loughran-McDonald dictionary cached permanently
- Model loaded once at startup

### Performance Considerations

- **Model Loading**: ~2-3 second startup time for ONNX model
- **SEC API**: Rate-limited external service, caching critical
- **Memory Usage**: Model and dictionary held in memory
- **Disk Usage**: Cache directory grows over time

## Security Analysis

### Current Security Posture

**Implemented:**
- Environment variables for sensitive configuration
- Stripe webhook signature verification
- Basic error handling to avoid information leakage

**Missing:**
- Input validation on API endpoints
- Rate limiting
- API key validation/rotation
- Request size limits
- CORS configuration
- Security headers

### Security Risks

1. **API Abuse**: No rate limiting on analysis endpoints
2. **Injection Attacks**: No input sanitization
3. **Resource Exhaustion**: No request size limits
4. **Information Disclosure**: Stack traces in error responses

## Appendix - Useful Commands and Scripts

### Frequently Used Commands

```bash
# Development
uvicorn api:app --reload     # Start development server
python main.py               # Direct analysis (CLI mode)
python benchmark_finbert.py  # Performance testing

# Code Quality
pre-commit run --all-files   # Run linting on all files
black .                      # Format code
flake8 .                     # Lint code

# Testing (when implemented)
pytest                       # Run tests
pytest --cov                 # Run with coverage
```

### Debugging and Troubleshooting

**Common Issues:**
- **Model Not Found**: Check `models/distilfinbert_onnx_q8/` directory exists
- **SEC API Errors**: Verify `SEC_API_KEY` in `.env` file
- **Stripe Errors**: Check Stripe keys and webhook secrets
- **Import Errors**: Ensure `load_dotenv()` called before importing `main`

**Logs and Monitoring:**
- **Application Logs**: Print statements to stdout (needs improvement)
- **Access Logs**: FastAPI default logging
- **Error Tracking**: Exception messages in HTTP responses

### File Size Considerations

- **Model Files**: ~100MB+ for ONNX models (not in git)
- **Dictionary File**: 9MB CSV file in repository
- **Cache Growth**: DiskCache directory grows with usage

---

## Summary for AI Agents

**What Edgar-Text Does:**
Provides dual-mode sentiment analysis of SEC 10-K filings using both traditional financial dictionaries and modern ML models, with integrated payment processing.

**Key Technical Patterns:**
- FastAPI for web API with automatic OpenAPI generation
- ONNX Runtime for optimized ML inference
- DiskCache for transparent API response caching
- Environment-based configuration
- Global model loading pattern

**Critical Constraints:**
- No existing test suite - implement before major changes
- Hard-coded file paths - consider making configurable
- Security gaps - add input validation and rate limiting
- Missing documentation - essential for maintainability

**Safe Areas for Modification:**
- Adding new API endpoints (follow existing patterns)
- Improving error handling and logging
- Adding configuration options
- Performance optimizations

**High-Risk Areas:**
- Model loading logic in `api.py:41-53`
- SEC API integration in `main.py:47-71`
- Payment webhook handling in `api.py:161-196`
- Cache configuration and file paths

This brownfield documentation reflects the ACTUAL state of a working system that needs quality improvements rather than architectural changes.