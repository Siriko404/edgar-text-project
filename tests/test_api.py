"""
Tests for the FastAPI application.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from api import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_sentiment_pipeline():
    """Mock the global sentiment pipeline."""
    mock_pipeline = {
        "tokenizer": MagicMock(),
        "model": MagicMock()
    }

    # Setup tokenizer mock
    mock_pipeline["tokenizer"].return_value = {
        "input_ids": [[1, 2, 3]],
        "attention_mask": [[1, 1, 1]]
    }

    # Setup model mock
    mock_outputs = MagicMock()
    mock_outputs.logits.argmax.return_value.item.return_value = 2  # Positive
    mock_probability = MagicMock()
    mock_probability.item.return_value = 0.7
    mock_outputs.logits.softmax.return_value = [
        [0.1, 0.2, mock_probability]
    ]  # Positive with 0.7 confidence
    mock_pipeline["model"].return_value = mock_outputs
    mock_pipeline["model"].config.id2label = {0: "negative", 1: "neutral", 2: "positive"}

    return mock_pipeline


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_root_endpoint(self, client):
        """Test the root health check endpoint."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "Edgar-Text API is running" in data["message"]


class TestSentimentAnalysis:
    """Test the sentiment analysis endpoint."""

    @patch("api.sentiment_pipeline")
    def test_analyze_sentiment_success(self, mock_pipeline_global, client, mock_sentiment_pipeline):
        """Test successful sentiment analysis."""
        mock_pipeline_global.__bool__.return_value = True
        mock_pipeline_global.__getitem__.side_effect = mock_sentiment_pipeline.__getitem__

        request_data = {"text": "The company reported excellent quarterly results."}
        response = client.post("/analyze/sentiment", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "POSITIVE"
        assert data["score"] == 0.7

    def test_analyze_sentiment_empty_text(self, client):
        """Test sentiment analysis with empty text."""
        request_data = {"text": ""}
        response = client.post("/analyze/sentiment", json=request_data)

        # Should still work with empty text (model handles it)
        assert response.status_code in [200, 422]  # 422 if validation fails

    def test_analyze_sentiment_invalid_request(self, client):
        """Test sentiment analysis with invalid request data."""
        response = client.post("/analyze/sentiment", json={})

        assert response.status_code == 422  # Validation error

    @patch("api.sentiment_pipeline", {})
    def test_analyze_sentiment_model_not_loaded(self, client):
        """Test sentiment analysis when model is not loaded."""
        request_data = {"text": "Test text"}
        response = client.post("/analyze/sentiment", json=request_data)

        assert response.status_code == 503
        assert "Model is not loaded" in response.json()["detail"]

    @patch("api.sentiment_pipeline")
    def test_analyze_sentiment_model_error(self, mock_pipeline_global, client):
        """Test sentiment analysis when model throws an error."""
        mock_pipeline_global.__bool__.return_value = True
        mock_pipeline_global.__getitem__.side_effect = Exception("Model inference error")

        request_data = {"text": "Test text"}
        response = client.post("/analyze/sentiment", json=request_data)

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]


class TestCompanyAnalysis:
    """Test the company analysis endpoint."""

    @patch("api.main.analyze_company")
    def test_get_analysis_success(self, mock_analyze, client):
        """Test successful company analysis."""
        mock_result = {
            "ticker": "AAPL",
            "latest_filing": {
                "filed_at": "2024-01-01",
                "gunning_fog_score": 12.5,
                "sentiment": {"positive_count": 10, "negative_count": 5}
            },
            "prior_filing": {
                "filed_at": "2023-01-01",
                "gunning_fog_score": 11.8,
                "sentiment": {"positive_count": 8, "negative_count": 7}
            },
            "comparison_metrics": {"change_score_similarity_ratio": 0.85}
        }
        mock_analyze.return_value = mock_result

        response = client.get("/analyze/AAPL")

        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert "latest_filing" in data
        assert "prior_filing" in data
        mock_analyze.assert_called_once_with("AAPL")

    @patch("api.main.analyze_company")
    def test_get_analysis_value_error(self, mock_analyze, client):
        """Test company analysis with invalid ticker."""
        mock_analyze.side_effect = ValueError("Invalid ticker")

        response = client.get("/analyze/INVAL")

        assert response.status_code == 404
        assert "Invalid ticker" in response.json()["detail"]

    @patch("api.main.analyze_company")
    def test_get_analysis_unexpected_error(self, mock_analyze, client):
        """Test company analysis with unexpected error."""
        mock_analyze.side_effect = Exception("Unexpected error")

        response = client.get("/analyze/AAPL")

        assert response.status_code == 500
        assert "An unexpected error occurred" in response.json()["detail"]


class TestAPIDocumentation:
    """Test API documentation endpoints."""

    def test_openapi_docs_available(self, client):
        """Test that OpenAPI documentation is available."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_redoc_available(self, client):
        """Test that ReDoc documentation is available."""
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_openapi_json(self, client):
        """Test OpenAPI JSON specification."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_spec = response.json()
        assert openapi_spec["info"]["title"] == "Edgar-Text API"
        assert "paths" in openapi_spec
        assert "/analyze/sentiment" in openapi_spec["paths"]
        assert "/analyze/{ticker}" in openapi_spec["paths"]


class TestTieredRateLimits:
    """Test tiered rate limiting and X-RateLimit-* headers."""

    def _clear_limits(self):
        from api import rate_limit_storage

        rate_limit_storage.clear()

    @patch("api.main.analyze_company")
    def test_anonymous_headers_present(self, mock_analyze, client):
        """Anonymous responses carry the 10/hour limit headers."""
        self._clear_limits()
        mock_analyze.return_value = {"ticker": "AAPL"}

        response = client.get("/analyze/AAPL")

        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == "10"
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    @patch("api.main.analyze_company")
    def test_anonymous_limit_enforced(self, mock_analyze, client):
        """The 11th anonymous request within the window is rejected."""
        self._clear_limits()
        mock_analyze.return_value = {"ticker": "AAPL"}

        for _ in range(10):
            assert client.get("/analyze/AAPL").status_code == 200
        response = client.get("/analyze/AAPL")
        assert response.status_code == 429

    @patch("api.main.analyze_company")
    def test_authenticated_higher_limit(self, mock_analyze, client):
        """An authenticated basic-tier caller sees the 1000/hour bucket."""
        self._clear_limits()
        mock_analyze.return_value = {"ticker": "AAPL"}
        from auth import get_current_user_optional
        from api import app as fastapi_app

        fastapi_app.dependency_overrides[get_current_user_optional] = lambda: {
            "user_id": "u1",
            "tier": "basic",
            "rate_limit": 1000,
            "auth_type": "jwt",
        }
        try:
            response = client.get("/analyze/AAPL")
        finally:
            fastapi_app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == "1000"
