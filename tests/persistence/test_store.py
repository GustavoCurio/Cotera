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


from tests.fakes import FakeResponses


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



@pytest.mark.postgres
def test_postgresql_persistence_and_decision(document, postgres_store):
    pg = postgres_store
    identifier = pg.create(demo_request())["id"]
    result = add_document(pg, identifier, (DATA/"proposals/aurora.pdf").read_bytes(), "aurora.pdf")
    snapshot = pg.get(identifier)
    assert snapshot["eligible_count"] == 1
    choice = Decision(proposal_id=result["id"], expected_version=snapshot["version"], actor="CI PostgreSQL", reason="Extração, comparação e persistência no PostgreSQL.")
    pg.decide(identifier, choice)
    with pytest.raises(ConflictError):
        pg.decide(identifier, choice)
    assert len(Store(pg.url).get(identifier)["decisions"]) == 1

