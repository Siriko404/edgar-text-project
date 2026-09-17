"""Tests for config parsing, auth store edges, and monitoring smoke."""

import pytest


class TestConfig:
    def test_validate_required_flags_missing(self, monkeypatch):
        import importlib

        import config

        monkeypatch.delenv("SEC_API_KEY", raising=False)
        importlib.reload(config)
        try:
            missing = config.validate_required()
            assert "SEC_API_KEY" in missing
        finally:
            importlib.reload(config)

    def test_list_parsing(self, monkeypatch):
        import importlib

        import config

        monkeypatch.setenv("CORS_ORIGINS", "https://a.com, https://b.com")
        monkeypatch.setenv("TRUSTED_HOSTS", "example.com")
        importlib.reload(config)
        try:
            assert config.CORS_ORIGINS == ["https://a.com", "https://b.com"]
            assert config.TRUSTED_HOSTS == ["example.com"]
        finally:
            importlib.reload(config)


class TestAuthStoreEdges:
    def test_blank_on_missing_file(self, tmp_path, monkeypatch):
        import auth_store

        monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "new.json"))
        data = auth_store.load_store()
        assert data == {"users": {}, "api_keys": {}}

    def test_blank_on_corrupt_file(self, tmp_path, monkeypatch):
        import auth_store

        store = tmp_path / "bad.json"
        store.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("AUTH_STORE_PATH", str(store))
        assert auth_store.load_store() == {"users": {}, "api_keys": {}}

    def test_create_user_bad_tier(self, tmp_path, monkeypatch):
        import auth_store

        monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "s.json"))
        with pytest.raises(ValueError, match="Unknown tier"):
            auth_store.create_user("x@example.com", "pw-123456", "gold")

    def test_set_tier_unknown_user(self, tmp_path, monkeypatch):
        import auth_store

        monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "s.json"))
        with pytest.raises(ValueError, match="not found"):
            auth_store.set_user_tier("ghost@example.com", "basic")

    def test_set_tier_roundtrip(self, tmp_path, monkeypatch):
        import auth_store

        monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "s.json"))
        auth_store.create_user("t@example.com", "pw-123456", "free")
        updated = auth_store.set_user_tier("t@example.com", "premium")
        assert updated["tier"] == "premium"

    def test_api_key_crud(self, tmp_path, monkeypatch):
        import auth_store

        monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "s.json"))
        assert auth_store.get_api_key("edgar_missing") is None
        auth_store.save_api_key(
            {
                "api_key": "edgar_abc",
                "key_id": "abc",
                "user_id": "u1",
                "tier": "basic",
                "rate_limit": 1000,
                "created_at": "2025-01-01T00:00:00",
                "last_used": None,
            }
        )
        assert auth_store.get_api_key("edgar_abc")["user_id"] == "u1"
        assert auth_store.list_api_keys() == ["abc"]
        auth_store.touch_api_key("edgar_abc", "2025-02-01T00:00:00")
        assert auth_store.delete_api_key_by_id("abc") is True
        assert auth_store.delete_api_key_by_id("abc") is False

    def test_password_check_rejects_malformed(self):
        import auth_store

        assert auth_store.check_password("anything", "not-a-hash") is False


class TestMonitoringSmoke:
    def test_counters_gauges_histograms(self):
        from monitoring import MetricsCollector, PerformanceMonitor

        collector = MetricsCollector()
        collector.record_counter("hits")
        collector.record_gauge("temp", 36.6)
        collector.record_histogram("lat", 0.5)
        summary = collector.get_summary()
        assert summary["counters"]["hits"] == 1
        assert summary["gauges"]["temp"] == 36.6
        with PerformanceMonitor("op"):
            pass
        filtered = collector.get_metrics("hits")
        assert "hits" in filtered

    def test_system_metrics_shape(self):
        from monitoring import metrics

        summary = metrics.get_summary()
        assert "timestamp" in summary
        assert "system" in summary
        assert isinstance(summary["system"], dict)


class TestAssetScript:
    def test_check_assets_reports_both_states(self, tmp_path, monkeypatch):
        import importlib

        import config

        dictionary = tmp_path / "dict.csv"
        dictionary.write_text("Word,X\nword,1\n", encoding="utf-8")
        monkeypatch.setenv("LM_DICTIONARY_PATH", str(dictionary))
        monkeypatch.setenv("MODEL_PATH", str(tmp_path / "models"))
        importlib.reload(config)
        try:
            import scripts.check_assets as check

            importlib.reload(check)
            assert check.main() == 1  # model missing
            model_dir = tmp_path / "models"
            model_dir.mkdir()
            (model_dir / "model_quantized.onnx").write_bytes(b"fake")
            assert check.main() == 0
        finally:
            importlib.reload(config)
