"""Tests del registry de adaptadores."""

import pytest

from app.adapters.registry import get_adapter, list_adapters


class TestAdapterRegistry:
    def test_sanitas_registered(self):
        adapter = get_adapter("sanitas")
        assert adapter.adapter_key == "sanitas"
        assert adapter.max_file_size_kb == 12288

    def test_sura_registered(self):
        adapter = get_adapter("sura")
        assert adapter.adapter_key == "sura"
        assert adapter.supports_radicacion is True
        assert adapter.supports_transcripcion is True

    def test_salud_total_registered(self):
        adapter = get_adapter("salud_total")
        assert adapter.adapter_key == "salud_total"
        assert adapter.max_file_size_kb == 4096

    def test_invalid_adapter(self):
        with pytest.raises(ValueError, match="No hay adaptador"):
            get_adapter("eps_inventada")

    def test_list_adapters(self):
        adapters = list_adapters()
        assert len(adapters) >= 3
        assert "sanitas" in adapters
        assert "sura" in adapters
        assert "salud_total" in adapters

        for key, meta in adapters.items():
            assert "eps_name" in meta
            assert "max_file_size_kb" in meta
            assert "supports_radicacion" in meta
