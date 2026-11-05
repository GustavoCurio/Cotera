"""Verificação dos limites, evidências, cálculos, transações, API e interface."""

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from cotera import api
from cotera.demo import DATA, demo_request
from cotera.documents import extract_template
from cotera.store import Store
from tests.fakes import FakeResponses

ROOT = DATA.parent


def test_api_end_to_end_auth_and_conflict(store, monkeypatch):
    monkeypatch.setattr(api, "store", lambda: store)
    with TestClient(api.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post("/requests", json=demo_request().model_dump(mode="json"))
        assert response.status_code == 201
        identifier = response.json()["id"]
        path = f"/requests/{identifier}"
        assert (
            client.post(
                path + "/proposals",
                files={"file": ("aurora.pdf", (DATA / "proposals/aurora.pdf").read_bytes(), "application/pdf")},
            ).status_code
            == 200
        )
        assert (
            client.post(path + "/proposals", data={"mode": "ai"}, files={"file": ("a.txt", b"test")}).status_code == 403
        )
        assert client.post(path + "/proposals", files={"file": ("a.exe", b"test")}).status_code == 422
        snapshot = client.get(path).json()
        decision = {
            "proposal_id": snapshot["lowest_cost_ids"][0],
            "expected_version": snapshot["version"],
            "actor": "Teste",
            "reason": "Comparação de prazo e valor concluída.",
        }
        assert client.post(path + "/decisions", json=decision).status_code == 201
        assert client.post(path + "/decisions", json=decision).status_code == 409
        assert client.get(path + "/report").status_code == 200
        assert client.get("/requests/missing").status_code == 404
        assert client.post("/requests/missing/proposals", files={"file": ("a.txt", b"test")}).status_code == 404
        monkeypatch.setenv("COTERA_API_KEY", "test-only")
        assert client.get("/requests").status_code == 401
        assert client.get("/requests", headers={"X-Cotera-Key": "test-only"}).status_code == 200


@pytest.mark.slow
def test_streamlit_comparison_decision_documents_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("COTERA_DATABASE_URL", "sqlite:///" + str(tmp_path / "own.sqlite3"))
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not ui.exception
    assert any("Prumo Distribuidora" in m.value for m in ui.markdown)
    next(t for t in ui.text_input if t.label == "Responsável pela escolha").set_value("Responsável de teste")
    next(t for t in ui.text_area if t.label == "Justificativa").set_value(
        "Prazo compatível e menor custo total conferido."
    )
    next(b for b in ui.button if b.label == "Registrar decisão").click().run()
    assert not ui.exception and ui.success
    ui.segmented_control[0].set_value("Decisões").run()
    assert not ui.exception
    assert any("Prazo compatível" in m.value for m in ui.markdown)
    ui.segmented_control[0].set_value("Documentos").run()
    assert not ui.exception
    assert len(ui.dataframe) == 1
    reader = next(r for r in ui.radio if r.label == "Leitura do documento")
    assert reader.options == ["Modelo Cotera · local"]
    assert reader.value == "Modelo Cotera · local"
    assert next(b for b in ui.button if b.label == "Extrair e adicionar").disabled
    next(s for s in ui.selectbox if s.label == "Espaço").set_value("Minhas cotações").run()
    assert not ui.exception
    assert any("primeira cotação" in item.value for item in ui.info)
    next(b for b in ui.button if b.label == "Carregar exemplo").click().run()
    assert not ui.exception
    assert ui.selectbox(key="cotera_space").value == "Demonstração"
    assert ui.segmented_control[0].value == "Comparar"
    assert any("Prumo Distribuidora" in m.value for m in ui.markdown)
    assert Store(os.environ["COTERA_DATABASE_URL"]).list() == []


@pytest.mark.slow
def test_streamlit_create_own_request(tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("COTERA_DATABASE_URL", "sqlite:///" + str(tmp_path / "own.sqlite3"))
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    next(s for s in ui.selectbox if s.label == "Espaço").set_value("Minhas cotações").run()
    next(b for b in ui.button if b.label == "＋ Nova cotação").click().run()
    assert not ui.exception
    next(n for n in ui.number_input if n.label == "Quantidade de itens na cesta").set_value(1).run()
    next(t for t in ui.text_input if t.label == "Nome da cotação").set_value("Uma compra própria")
    next(t for t in ui.text_input if t.label == "Código 1").set_value("TESTE-01")
    next(t for t in ui.text_input if t.label == "Descrição 1").set_value("Material para verificação")
    next(b for b in ui.button if b.label == "Criar cotação").click().run()
    assert not ui.exception
    assert ui.segmented_control[0].value == "Documentos"
    own = Store("sqlite:///" + str(tmp_path / "own.sqlite3")).list()
    assert len(own) == 1 and own[0]["items"][0]["sku"] == "TESTE-01"


@pytest.mark.slow
@pytest.mark.parametrize("scanned", [False, True])
def test_example_buttons_give_feedback_and_do_not_duplicate(tmp_path, monkeypatch, scanned):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path))
    calls = []

    def fake_ocr(content, indexes):
        calls.append(indexes)
        return {0: ((DATA / "proposals/aurora.txt").read_text(), 95.0)}

    monkeypatch.setattr("cotera.documents.read_scanned_pages", fake_ocr)
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    ui.segmented_control[0].set_value("Documentos").run()
    label = "Carregar exemplo escaneado" if scanned else "Carregar exemplo"
    snapshots = []
    for _ in range(2):
        next(b for b in ui.button if b.label == label).click().run()
        assert not ui.exception
        assert any("Aurora Suprimentos" in s.value and "Comparar" in s.value for s in ui.success)
        snapshots.append(
            Store("sqlite:///" + str(tmp_path / "demo.sqlite3")).get(ui.selectbox(key="cotera_purchase").value)
        )
    first, second = snapshots
    assert first["id"] == second["id"] and first["version"] == second["version"]
    assert len(second["proposals"]) == 3
    assert sum(p["draft"]["supplier"] == "Aurora Suprimentos" for p in second["proposals"]) == 1
    assert sum(p["audit"]["requires_human_review"] for p in second["proposals"]) == int(scanned)
    assert len(calls) == int(scanned)  # Reenvio não repete nem o OCR.
    if scanned:
        next(b for b in ui.button if b.label == "Carregar exemplo").click().run()
        assert not ui.exception and ui.segmented_control[0].value == "Comparar"
        regular = Store("sqlite:///" + str(tmp_path / "demo.sqlite3")).get(ui.selectbox(key="cotera_purchase").value)
        assert len(regular["proposals"]) == 3
        assert not any(p["audit"]["requires_human_review"] for p in regular["proposals"])


@pytest.mark.slow
@pytest.mark.parametrize("source", ["env", "secrets"])
@pytest.mark.parametrize("configured_model", [False, True])
def test_streamlit_ai_requires_key_and_defaults_to_local(tmp_path, monkeypatch, source, configured_model):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    settings = {"OPENAI_API_KEY": "chave-ficticia-para-teste"}
    if configured_model:
        settings["OPENAI_MODEL"] = "modelo-simulado"
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    if source == "env":
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
    else:
        ui.secrets.update(settings)
    ui.run()
    ui.segmented_control[0].set_value("Documentos").run()
    assert not ui.exception
    reader = next(r for r in ui.radio if r.label == "Leitura do documento")
    assert reader.options == ["Modelo Cotera · local", "Extração com IA"]
    assert reader.value == "Modelo Cotera · local"
    reader.set_value("Extração com IA").run()
    assert not ui.exception
    model = next(t for t in ui.text_input if t.label == "Modelo da OpenAI")
    assert model.value == settings.get("OPENAI_MODEL", "")
    assert not ui.checkbox[0].value
    assert next(b for b in ui.button if b.label == "Extrair e adicionar").disabled


@pytest.mark.slow
def test_streamlit_model_without_key_does_not_offer_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("OPENAI_MODEL", "modelo-simulado")
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    ui.segmented_control[0].set_value("Documentos").run()
    assert not ui.exception
    assert ui.radio[0].options == ["Modelo Cotera · local"]


@pytest.mark.slow
def test_ai_metrics_in_api_persistence_and_streamlit(store, document, tmp_path, monkeypatch):
    responses = FakeResponses(
        extract_template(document).model_dump(mode="json"),
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ),
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: SimpleNamespace(responses=responses))
    monkeypatch.setenv("OPENAI_API_KEY", "chave-ficticia")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setattr(api, "store", lambda: store)
    identifier = store.create(demo_request())["id"]
    with TestClient(api.app) as client:
        route = f"/requests/{identifier}/proposals"
        kwargs = {
            "files": {"file": ("aurora.txt", (DATA / "proposals/aurora.txt").read_bytes())},
            "data": {"mode": "ai", "approve_external_processing": "true"},
        }
        first = client.post(route, **kwargs)
        second = client.post(route, **kwargs)
        assert first.status_code == second.status_code == 200
        assert first.json()["created"] and not second.json()["created"]
        meta = first.json()["extraction"]
        assert meta == second.json()["extraction"] == store.get(identifier)["proposals"][0]["extraction"]
        assert meta["attempts"] == 1 and meta["usage"]["reasoning_tokens"] == 10
        assert meta["estimated_cost_usd"] == "0.00012" and meta["pricing_date"]
        assert len(responses.calls) == 1
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("COTERA_DATABASE_URL", store.url)
    monkeypatch.delenv("OPENAI_API_KEY")
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    ui.selectbox(key="cotera_space").set_value("Minhas cotações").run()
    ui.segmented_control[0].set_value("Documentos").run()
    assert not ui.exception
    assert any("raciocínio 10" in c.value and "cache 20" in c.value for c in ui.caption)
    assert any("custo estimado: US$ 0.00012" in c.value and "Tentativas: 1" in c.value for c in ui.caption)


def test_api_provider_error_is_typed_safe_and_keeps_usage(store, document, monkeypatch):
    responses = FakeResponses(
        {**extract_template(document).model_dump(mode="json"), "freight": "999"},
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: SimpleNamespace(responses=responses))
    monkeypatch.setenv("OPENAI_API_KEY", "chave-ficticia-secreta")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setattr(api, "store", lambda: store)
    identifier = store.create(demo_request())["id"]
    with TestClient(api.app) as client:
        result = client.post(
            f"/requests/{identifier}/proposals",
            files={"file": ("aurora.txt", (DATA / "proposals/aurora.txt").read_bytes())},
            data={"mode": "ai", "approve_external_processing": "true"},
        )
    assert result.status_code == 502
    detail = result.json()["detail"]
    assert detail["code"] == "extraction_evidence" and "evidência válida" in detail["message"]
    assert detail["extraction"]["usage"]["input_tokens"] == 200
    assert "secreta" not in result.text and store.get(identifier)["proposals"] == []
