"""Verificação dos limites, evidências, cálculos, transações, API e interface."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from streamlit.testing.v1 import AppTest
from cotera import api
from cotera import store as store_module
from cotera.comparison import audit_quote, compare
from cotera.demo import DATA, demo_request, seed_demo
from cotera.documents import MAX_BYTES, br_number, extract_template, read_document, verify_evidence
from cotera.evaluation import evaluate
from cotera.extraction import ProviderError, extract
from cotera.models import Decision, PurchaseRequest, QuoteDraft
from cotera.reports import comparison_csv, report_html, snapshot_json
from cotera.service import add_document
from cotera.store import ConflictError, Store

ROOT = DATA.parent


@pytest.fixture
def store(tmp_path):
    return Store("sqlite:///" + str(tmp_path / "cotera.sqlite3"))


@pytest.fixture
def document():
    return read_document((DATA / "proposals/aurora.txt").read_bytes(), "aurora.txt")


@pytest.fixture(autouse=True)
def no_external_credentials(monkeypatch):
    for name in ["OPENAI_API_KEY", "OPENAI_MODEL", "COTERA_API_KEY", "COTERA_DB_PASSWORD"]:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("text,value", [("R$ 1.405,00", "1405"), ("0,00", "0"), ("1,125", "1.125"), ("1.000", "1000")])
def test_brazilian_numbers(text, value):
    assert br_number(text) == Decimal(value)


@pytest.mark.parametrize("text", ["12.50", "1.23,00", "1e3", "NaN", "Infinity", "R$", "1,2345"])
def test_ambiguous_or_unbounded_numbers_rejected(text):
    with pytest.raises(ValueError):
        br_number(text)


def test_pdf_and_txt_produce_same_draft(document):
    pdf = read_document((DATA / "proposals/aurora.pdf").read_bytes(), "aurora.pdf")
    first, second = extract_template(document), extract_template(pdf)
    assert first.model_dump(exclude={"evidence", "items"}) == second.model_dump(exclude={"evidence", "items"})
    assert first.items[0].unit_price == second.items[0].unit_price == Decimal("32")
    verify_evidence(second, pdf)


@pytest.mark.parametrize("content,name", [(b"", "a.txt"), (b"x"*(MAX_BYTES+1), "a.txt"), (b"bad", "a.exe"), (b"\xff", "a.txt"), (b"bad", "a.pdf"), (b" ", "a.txt"), (b"x"*25001, "a.txt")])
def test_document_limits(content, name):
    with pytest.raises(ValueError):
        read_document(content, name)


def test_pdf_encrypted_blank_and_page_limit():
    for pages, encrypted in [(1, False), (6, False), (1, True)]:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=200, height=200)
        if encrypted:
            writer.encrypt("secret")
        stream = BytesIO()
        writer.write(stream)
        with pytest.raises(ValueError):
            read_document(stream.getvalue(), "blank.pdf")


def test_sources_are_checked_and_missing_values_stay_missing(document):
    draft = extract_template(document)
    draft.freight = Decimal("999.00")
    with pytest.raises(ValueError, match="correspondência"):
        verify_evidence(draft, document)
    without = "\n".join(line for line in document.lines if not line.startswith("Frete:"))
    partial = extract_template(read_document(without.encode(), "partial.txt"))
    assert partial.freight is None
    assert partial.evidence.freight is None
    assert not audit_quote(demo_request(), partial)["eligible"]


def test_bad_line_and_repeated_root_fields(document):
    draft = extract_template(document)
    draft.evidence.supplier = 999
    with pytest.raises(ValueError):
        verify_evidence(draft, document)
    content = ("\n".join(document.lines) + "\nFrete: R$ 0,00").encode()
    with pytest.raises(ValueError, match="repetido"):
        extract_template(read_document(content, "duplicate.txt"))


def test_request_and_decimal_contracts(document):
    request = demo_request().model_dump(mode="json")
    request["items"].append(request["items"][0])
    with pytest.raises(ValidationError):
        PurchaseRequest.model_validate(request)
    payload = extract_template(document).model_dump(mode="json")
    for value in ["-1", "NaN", "12.345", "100000001"]:
        altered = deepcopy(payload)
        altered["freight"] = value
        with pytest.raises(ValidationError):
            QuoteDraft.model_validate(altered)


def test_round_half_up_and_unit_and_deadline(document):
    request = PurchaseRequest(title="Uma unidade", items=[{"sku": "AB", "description": "Item fracionável", "quantity": "0.125", "unit": "kg"}])
    draft = QuoteDraft(supplier="Teste", reference="01", currency="BRL", delivery_days=5, freight="0", discount="0", reported_total="0.13",
                       items=[{"sku": "AB", "quantity": "0.125", "unit": "kg", "unit_price": "1", "source_line": 1}])
    assert audit_quote(request, draft)["computed_total"] == "0.13"
    assert audit_quote(request, draft)["eligible"]
    draft.items[0].unit = "un"
    assert not audit_quote(request, draft)["eligible"]
    deadline = demo_request().model_copy(update={"max_delivery_days": 4})
    assert not audit_quote(deadline, extract_template(document))["eligible"]


def test_golden_cases_and_no_cheapest_invalid_quote(store):
    result = evaluate()
    assert result["passed"] == result["total"] == 8
    identifier = seed_demo(store)
    snapshot = store.get(identifier)
    assert snapshot["eligible_count"] == 2
    assert snapshot["lowest_cost"] == "1320.00"
    lowest = next(p for p in snapshot["proposals"] if p["id"] in snapshot["lowest_cost_ids"])
    assert lowest["draft"]["supplier"] == "Prumo Distribuidora"
    invalid = next(p for p in snapshot["proposals"] if p["draft"]["supplier"] == "Vértice Comercial")
    assert invalid["audit"]["computed_total"] == "1350.00"
    assert not invalid["audit"]["eligible"]
    # Empates precisam retornar todas as alternativas de menor custo.
    copied = deepcopy(lowest)
    copied["id"] = "f"*32
    tied = compare(demo_request(), [lowest, copied])
    assert len(tied["lowest_cost_ids"]) == 2


def test_same_document_deduplicates_without_changing_version(store, document):
    identifier = store.create(demo_request())["id"]
    first = add_document(store, identifier, (DATA/"proposals/aurora.txt").read_bytes(), "a.txt")
    before = store.get(identifier)["version"]
    second = add_document(store, identifier, (DATA/"proposals/aurora.txt").read_bytes(), "renamed.txt", "ai", consent=True)
    assert first["created"] and not second["created"]
    assert first["id"] == second["id"]
    assert store.get(identifier)["version"] == before
    assert len(Store(store.url).get(identifier)["proposals"]) == 1


def test_decision_conflict_ineligible_and_history(store):
    identifier = seed_demo(store)
    snapshot = store.get(identifier)
    body = Decision(proposal_id=snapshot["lowest_cost_ids"][0], expected_version=snapshot["version"], actor="Operador de teste", reason="O custo atende ao orçamento e o prazo foi considerado.")
    first = store.decide(identifier, body)
    assert first["total"] == "1320.00"
    with pytest.raises(ConflictError):
        store.decide(identifier, body)
    updated = store.get(identifier)
    body.expected_version = updated["version"]
    store.decide(identifier, body)
    assert len(store.get(identifier)["decisions"]) == 2
    body.proposal_id = next(p["id"] for p in snapshot["proposals"] if not p["audit"]["eligible"])
    with pytest.raises(ValueError):
        store.decide(identifier, body)
    with pytest.raises(KeyError):
        store.get("missing")


def test_transaction_rollback_and_sql_is_data(store):
    malicious = demo_request().model_copy(update={"title": "'; DROP TABLE purchases; --"})
    identifier = store.create(malicious)["id"]
    assert store.get(identifier)["request"]["title"] == malicious.title
    with pytest.raises(RuntimeError):
        with store.connection(write=True) as connection:
            store.execute(connection, "UPDATE purchases SET version=99 WHERE id=?", (identifier,))
            raise RuntimeError("rollback")
    assert store.get(identifier)["version"] == 1


class FakeResponses:
    def __init__(self, payload, status="completed"):
        self.payload, self.status, self.calls = payload, status, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload), status=self.status)


def test_ai_requires_consent_and_checks_schema_and_evidence(document):
    payload = extract_template(document).model_dump(mode="json")
    responses = FakeResponses(payload)
    client = SimpleNamespace(responses=responses)
    with pytest.raises(PermissionError):
        extract(document, demo_request(), "ai", client=client, model="test")
    assert not responses.calls
    draft, meta = extract(document, demo_request(), "ai", consent=True, client=client, model="test")
    assert draft.supplier == "Aurora Suprimentos" and meta["mode"] == "ai"
    call = responses.calls[0]
    assert call["store"] is False
    assert call["text"]["format"]["strict"] is True
    assert len(json.loads(call["input"])["document"]) == len(document.lines)
    responses.payload["freight"] = "999"
    with pytest.raises(ProviderError):
        extract(document, demo_request(), "ai", consent=True, client=client, model="test")
    responses.payload = payload
    responses.status = "incomplete"
    with pytest.raises(ProviderError):
        extract(document, demo_request(), "ai", consent=True, client=client, model="test")


def test_ai_configuration_and_unknown_mode(document):
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        extract(document, demo_request(), "ai", consent=True)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        extract(document, demo_request(), "ai", consent=True, model="test")
    with pytest.raises(ValueError):
        extract(document, demo_request(), "invalid")


def test_brl_currency_can_be_grounded_in_explicit_currency_symbol(document):
    draft = extract_template(document)
    draft.evidence.currency = draft.evidence.freight
    verify_evidence(draft, document)
    draft.evidence.currency = draft.evidence.delivery_days
    with pytest.raises(ValueError):
        verify_evidence(draft, document)


def test_exports_escape_html_and_neutralize_formulas(store):
    snapshot = store.get(seed_demo(store))
    snapshot["request"]["title"] = "<script>alert(1)</script>"
    snapshot["proposals"][0]["draft"]["supplier"] = "=HYPERLINK(1)"
    html = report_html(snapshot).decode()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "'=HYPERLINK(1)" in comparison_csv(snapshot).decode("utf-8-sig")
    assert json.loads(snapshot_json(snapshot))["request"]["title"] == snapshot["request"]["title"]


def test_api_end_to_end_auth_and_conflict(store, monkeypatch):
    monkeypatch.setattr(api, "store", lambda: store)
    with TestClient(api.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post("/requests", json=demo_request().model_dump(mode="json"))
        assert response.status_code == 201
        identifier = response.json()["id"]
        path = f"/requests/{identifier}"
        assert client.post(path+"/proposals", files={"file": ("aurora.pdf", (DATA/"proposals/aurora.pdf").read_bytes(), "application/pdf")}).status_code == 200
        assert client.post(path+"/proposals", data={"mode": "ai"}, files={"file": ("a.txt", b"test")}).status_code == 403
        assert client.post(path+"/proposals", files={"file": ("a.exe", b"test")}).status_code == 422
        snapshot = client.get(path).json()
        decision = {"proposal_id": snapshot["lowest_cost_ids"][0], "expected_version": snapshot["version"], "actor": "Teste", "reason": "Comparação de prazo e valor concluída."}
        assert client.post(path+"/decisions", json=decision).status_code == 201
        assert client.post(path+"/decisions", json=decision).status_code == 409
        assert client.get(path+"/report").status_code == 200
        assert client.get("/requests/missing").status_code == 404
        assert client.post("/requests/missing/proposals", files={"file": ("a.txt", b"test")}).status_code == 404
        monkeypatch.setenv("COTERA_API_KEY", "test-only")
        assert client.get("/requests").status_code == 401
        assert client.get("/requests", headers={"X-Cotera-Key": "test-only"}).status_code == 200


def test_streamlit_comparison_decision_documents_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("COTERA_DATABASE_URL", "sqlite:///" + str(tmp_path / "own.sqlite3"))
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not ui.exception
    assert any("Prumo Distribuidora" in m.value for m in ui.markdown)
    next(t for t in ui.text_input if t.label == "Responsável pela escolha").set_value("Responsável de teste")
    next(t for t in ui.text_area if t.label == "Justificativa").set_value("Prazo compatível e menor custo total conferido.")
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


def test_concurrent_decisions_only_one_wins(store):
    identifier = seed_demo(store)
    snapshot = store.get(identifier)
    decision = Decision(proposal_id=snapshot["lowest_cost_ids"][0], expected_version=snapshot["version"], actor="Teste", reason="Conferência concorrente da mesma fotografia.")
    def submit():
        try:
            store.decide(identifier, decision)
            return "saved"
        except ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(outcomes) == ["conflict", "saved"]
    assert len(store.get(identifier)["decisions"]) == 1


def test_proposal_limit_and_nonexistent_choice(store, document):
    identifier = store.create(demo_request())["id"]
    for i in range(10):
        add_document(store, identifier, ("\n".join(document.lines)+f"\nNota: {i}").encode(), f"quote{i}.txt")
    with pytest.raises(ValueError, match="dez propostas"):
        add_document(store, identifier, ("\n".join(document.lines)+"\nNota: 11").encode(), "quote11.txt")
    with pytest.raises(ValueError):
        store.decide(identifier, Decision(proposal_id="f"*32, expected_version=11, actor="Teste", reason="Fornecedor inexistente nesta comparação."))


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


def test_streamlit_model_without_key_does_not_offer_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path / "demo"))
    monkeypatch.setenv("OPENAI_MODEL", "modelo-simulado")
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    ui.segmented_control[0].set_value("Documentos").run()
    assert not ui.exception
    assert ui.radio[0].options == ["Modelo Cotera · local"]


def test_ai_receives_server_credentials_without_saving_key(store, document, monkeypatch):
    responses = FakeResponses(extract_template(document).model_dump(mode="json"))
    options = {}

    def fake_openai(**kwargs):
        options.update(kwargs)
        return SimpleNamespace(responses=responses)

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    identifier = store.create(demo_request())["id"]
    add_document(store, identifier, (DATA / "proposals/aurora.txt").read_bytes(), "aurora.txt", "ai",
                 consent=True, model="modelo-simulado", api_key="chave-ficticia-para-teste")
    assert options == {"api_key": "chave-ficticia-para-teste", "timeout": 30, "max_retries": 0}
    assert responses.calls[0]["model"] == "modelo-simulado"
    snapshot = store.get(identifier)
    assert snapshot["eligible_count"] == 1
    assert "chave-ficticia-para-teste" not in snapshot_json(snapshot).decode()


@pytest.mark.parametrize("failure", ["directory", "journal", "database"])
def test_default_sqlite_falls_back_to_writable_tempdir(tmp_path, monkeypatch, failure):
    root = tmp_path / "project"
    root.mkdir()
    storage = root / "storage"
    monkeypatch.setattr(store_module, "ROOT", root)
    monkeypatch.setattr(store_module.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
    monkeypatch.delenv("COTERA_DATABASE_URL", raising=False)
    if failure == "directory":
        storage.write_text("Impede a criação do diretório padrão.")
    elif failure == "journal":
        original_temporary_file = store_module.tempfile.TemporaryFile

        def temporary_file(*args, **kwargs):
            if kwargs.get("dir") == storage:
                raise PermissionError("Diretório padrão somente para leitura.")
            return original_temporary_file(*args, **kwargs)

        monkeypatch.setattr(store_module.tempfile, "TemporaryFile", temporary_file)
    else:
        original_open = Path.open

        def open_path(path, *args, **kwargs):
            if path.parent == storage:
                raise PermissionError("Banco padrão somente para leitura.")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_path)

    own = Store()
    assert own.path == tmp_path / "temp" / "cotera" / "cotera.sqlite3"
    identifier = own.create(demo_request())["id"]
    assert Store().get(identifier)["request"]["title"] == demo_request().title
    demo = Store(store_module.default_sqlite_url("demo.sqlite3"))
    assert demo.path != own.path
    assert demo.list() == []
    assert len(demo.get(seed_demo(demo))["proposals"]) == 3


def test_explicit_sqlite_configuration_does_not_silently_fall_back(tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("Configuração explícita inválida.")
    url = "sqlite:///" + str(blocked / "database.sqlite3")
    with pytest.raises(OSError):
        Store(url)
    monkeypatch.setenv("COTERA_DATABASE_URL", url)
    with pytest.raises(OSError):
        Store()


@pytest.mark.skipif(not os.environ.get("COTERA_TEST_POSTGRES_URL"), reason="Requer PostgreSQL; executado no job de integração do CI.")
def test_postgresql_persistence_and_decision(document):
    pg = Store(os.environ["COTERA_TEST_POSTGRES_URL"])
    identifier = pg.create(demo_request())["id"]
    result = add_document(pg, identifier, (DATA/"proposals/aurora.pdf").read_bytes(), "aurora.pdf")
    snapshot = pg.get(identifier)
    assert snapshot["eligible_count"] == 1
    choice = Decision(proposal_id=result["id"], expected_version=snapshot["version"], actor="CI PostgreSQL", reason="Extração, comparação e persistência no PostgreSQL.")
    pg.decide(identifier, choice)
    with pytest.raises(ConflictError):
        pg.decide(identifier, choice)
    assert len(Store(pg.url).get(identifier)["decisions"]) == 1
