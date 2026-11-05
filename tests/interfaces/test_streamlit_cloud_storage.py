"""Regressão: demonstração Streamlit sem DATABASE_URL e storage do repo inacessível."""

import os

import pytest
from streamlit.testing.v1 import AppTest

import cotera.store as store_module
import inspect

from cotera.demo import DATA, seed_demo

ROOT = DATA.parent


@pytest.mark.slow
def test_streamlit_demo_without_database_url_uses_temp_storage(tmp_path, monkeypatch):
    """Community Cloud: sem variáveis de banco e sem gravação em storage/ do projeto."""
    monkeypatch.delenv("COTERA_DATABASE_URL", raising=False)
    monkeypatch.delenv("COTERA_DEMO_HOME", raising=False)
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "readonly-project")
    (tmp_path / "readonly-project").mkdir()
    # Impede o diretório padrão: storage vira um arquivo, como no teste de persistência.
    (tmp_path / "readonly-project" / "storage").write_text("somente leitura")
    monkeypatch.setattr(store_module.tempfile, "gettempdir", lambda: str(tmp_path / "cloud-tmp"))

    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not ui.exception
    assert not any("armazenamento" in getattr(e, "value", "").lower() for e in ui.error)
    assert any("Prumo Distribuidora" in m.value for m in ui.markdown)
    assert any("MENOR CUSTO ELEGÍVEL" in m.value for m in ui.markdown)
    assert any("R$ 1.320,00" in m.value for m in ui.markdown)

    next(b for b in ui.button if b.label == "Carregar exemplo").click().run()
    assert not ui.exception
    assert not any("armazenamento" in getattr(e, "value", "").lower() for e in ui.error)
    assert ui.selectbox(key="cotera_space").value == "Demonstração"
    assert any("Prumo Distribuidora" in m.value for m in ui.markdown)
    assert any("MENOR CUSTO ELEGÍVEL" in m.value for m in ui.markdown)
    assert any("R$ 1.320,00" in m.value for m in ui.markdown)
    assert os.environ.get("COTERA_DATABASE_URL") is None
    assert "scanned" in inspect.signature(seed_demo).parameters
