"""Tests de configuración y eps_config."""

import pytest

from app.config import Settings
from app.eps_config import EPSConfig, get_eps_config, load_eps_configs, validate_file_size


class TestSettings:
    def test_default_values(self):
        s = Settings(internal_token="test-token")
        assert s.app_env == "development"
        assert s.playwright_headless is True

    def test_allowed_hosts_list(self):
        s = Settings(internal_token="t", callback_allowed_hosts="a.com, b.com, c.com")
        assert s.allowed_hosts_list == ["a.com", "b.com", "c.com"]


class TestEPSConfig:
    def test_load_configs(self):
        configs = load_eps_configs()
        assert len(configs) >= 8
        assert "sanitas" in configs
        assert "sura" in configs
        assert "salud_total" in configs

    def test_get_sanitas(self):
        cfg = get_eps_config("sanitas")
        assert cfg.eps_code == "SANITAS"
        assert cfg.max_file_size_kb == 12288

    def test_get_compensar(self):
        cfg = get_eps_config("compensar")
        assert cfg.max_file_size_kb == 900

    def test_validate_file_size_ok(self):
        assert validate_file_size("sanitas", 5000) is True

    def test_validate_file_size_too_large(self):
        assert validate_file_size("compensar", 1000) is False

    def test_invalid_adapter_key(self):
        with pytest.raises(ValueError, match="no encontrada"):
            get_eps_config("eps_inexistente")
