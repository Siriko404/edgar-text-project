"""
Tests for the main analysis engine.
"""

import pytest
from unittest.mock import patch, mock_open, MagicMock
from main import (
    load_lm_dictionary,
    calculate_lm_sentiment,
    analyze_company,
    get_latest_10k_filings,
    get_risk_factors_text,
)


class TestLMDictionary:
    """Test Loughran-McDonald dictionary loading and processing."""

    @patch("builtins.open", new_callable=mock_open, read_data="word,0,0,0,0,0,0,1,1\ntest,0,0,0,0,0,1,0,0\n")
    def test_load_lm_dictionary_success(self, mock_file):
        """Test successful loading of LM dictionary."""
        positive_words, negative_words = load_lm_dictionary()

        assert "word" in positive_words
        assert "test" in negative_words
        assert len(positive_words) == 1
        assert len(negative_words) == 1

    @patch("builtins.open", side_effect=FileNotFoundError())
    def test_load_lm_dictionary_file_not_found(self, mock_file):
        """Test handling of missing dictionary file."""
        positive_words, negative_words = load_lm_dictionary()

        assert positive_words == set()
        assert negative_words == set()

    def test_calculate_lm_sentiment(self):
        """Test sentiment calculation with word counts."""
        positive_words = {"good", "excellent", "positive"}
        negative_words = {"bad", "terrible", "negative"}

        text = "This is a good and excellent result, not bad"
        result = calculate_lm_sentiment(text, positive_words, negative_words)

        assert result["positive_count"] == 2  # "good", "excellent"
        assert result["negative_count"] == 1  # "bad"

    def test_calculate_lm_sentiment_empty_text(self):
        """Test sentiment calculation with empty text."""
        positive_words = {"good"}
        negative_words = {"bad"}

        result = calculate_lm_sentiment("", positive_words, negative_words)

        assert result["positive_count"] == 0
        assert result["negative_count"] == 0


class TestSECAPI:
    """Test SEC API integration functions."""

    @patch("main.queryApi.get_filings")
    def test_get_latest_10k_filings_success(self, mock_get_filings):
        """Test successful retrieval of 10-K filings."""
        mock_response = {
            "filings": [
                {"filedAt": "2024-01-01", "linkToFilingDetails": "url1"},
                {"filedAt": "2023-01-01", "linkToFilingDetails": "url2"},
            ]
        }
        mock_get_filings.return_value = mock_response

        result = get_latest_10k_filings("AAPL")

        assert len(result) == 2
        assert result[0]["filedAt"] == "2024-01-01"

        # Verify query structure
        mock_get_filings.assert_called_once()
        call_args = mock_get_filings.call_args[0][0]
        assert 'ticker:AAPL' in call_args["query"]["query_string"]["query"]
        assert 'formType:"10-K"' in call_args["query"]["query_string"]["query"]

    @patch("main.queryApi.get_filings")
    def test_get_latest_10k_filings_empty_response(self, mock_get_filings):
        """Test handling of empty SEC API response."""
        mock_get_filings.return_value = {"filings": []}

        result = get_latest_10k_filings("INVALID")

        assert result == []

    @patch("main.extractorApi.get_section")
    def test_get_risk_factors_text_success(self, mock_get_section):
        """Test successful extraction of risk factors text."""
        mock_get_section.return_value = "Sample risk factors text."

        result = get_risk_factors_text("https://example.com/filing")

        assert result == "Sample risk factors text."
        mock_get_section.assert_called_once_with("https://example.com/filing", "1A", "text")


class TestAnalyzeCompany:
    """Test the main company analysis function."""

    @patch("main.load_lm_dictionary")
    @patch("main.get_latest_10k_filings")
    @patch("main.get_risk_factors_text")
    @patch("textstat.gunning_fog")
    def test_analyze_company_success(
        self, mock_gunning_fog, mock_get_risk_factors, mock_get_filings, mock_load_dict
    ):
        """Test successful company analysis."""
        # Setup mocks
        mock_load_dict.return_value = ({"good"}, {"bad"})
        mock_get_filings.return_value = [
            {"filedAt": "2024-01-01", "linkToFilingDetails": "url1"},
            {"filedAt": "2023-01-01", "linkToFilingDetails": "url2"},
        ]
        mock_get_risk_factors.side_effect = [
            "This is good news for investors",
            "This might be bad for the company"
        ]
        mock_gunning_fog.side_effect = [12.5, 11.8]

        result = analyze_company("AAPL")

        # Verify structure
        assert "ticker" in result
        assert "latest_filing" in result
        assert "prior_filing" in result
        assert "comparison_metrics" in result

        # Verify content
        assert result["ticker"] == "AAPL"
        assert result["latest_filing"]["gunning_fog_score"] == 12.5
        assert result["latest_filing"]["sentiment"]["positive_count"] == 1
        assert result["prior_filing"]["sentiment"]["negative_count"] == 1

    @patch("main.load_lm_dictionary")
    @patch("main.get_latest_10k_filings")
    def test_analyze_company_insufficient_filings(self, mock_get_filings, mock_load_dict):
        """Test handling of insufficient filings."""
        mock_load_dict.return_value = (set(), set())
        mock_get_filings.return_value = [{"filedAt": "2024-01-01"}]  # Only one filing

        result = analyze_company("INVALID")

        assert "error" in result
        assert "Could not retrieve two 10-K filings" in result["error"]

    @patch("main.load_lm_dictionary")
    @patch("main.get_latest_10k_filings")
    @patch("main.get_risk_factors_text")
    def test_analyze_company_extraction_failure(
        self, mock_get_risk_factors, mock_get_filings, mock_load_dict
    ):
        """Test handling of risk factors extraction failure."""
        mock_load_dict.return_value = (set(), set())
        mock_get_filings.return_value = [
            {"linkToFilingDetails": "url1"},
            {"linkToFilingDetails": "url2"},
        ]
        mock_get_risk_factors.side_effect = [None, "Some text"]  # First extraction fails

        result = analyze_company("AAPL")

        assert "error" in result
        assert "Failed to extract risk factors" in result["error"]


# Integration test (requires actual dependencies)
class TestIntegration:
    """Integration tests that require environment setup."""

    @pytest.mark.skipif(
        "not config.getoption('--integration')",
        reason="Need --integration option to run"
    )
    def test_load_actual_dictionary(self):
        """Test loading actual LM dictionary file (if present)."""
        try:
            positive_words, negative_words = load_lm_dictionary()
            # If file exists, we should get some words
            if positive_words or negative_words:
                assert len(positive_words) > 0
                assert len(negative_words) > 0
        except Exception:
            pytest.skip("LM dictionary file not available")


def pytest_addoption(parser):
    """Add command line options for pytest."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests"
    )