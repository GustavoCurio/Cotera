"""Verificação dos limites, evidências, cálculos, transações, API e interface."""

import json
from types import SimpleNamespace

import pytest

from cotera.demo import DATA, demo_request
from cotera.documents import extract_template, verify_evidence
from cotera.extraction import ProviderError, extract
from cotera.reports import snapshot_json
from cotera.service import add_document
from tests.fakes import FakeResponses

ROOT = DATA.parent


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


def test_ai_receives_server_credentials_without_saving_key(store, document, monkeypatch):
    responses = FakeResponses(extract_template(document).model_dump(mode="json"))
    options = {}

    def fake_openai(**kwargs):
        options.update(kwargs)
        return SimpleNamespace(responses=responses)

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    identifier = store.create(demo_request())["id"]
    add_document(
        store,
        identifier,
        (DATA / "proposals/aurora.txt").read_bytes(),
        "aurora.txt",
        "ai",
        consent=True,
        model="modelo-simulado",
        api_key="chave-ficticia-para-teste",
    )
    assert options == {"api_key": "chave-ficticia-para-teste", "timeout": 30, "max_retries": 0}
    assert responses.calls[0]["model"] == "modelo-simulado"
    snapshot = store.get(identifier)
    assert snapshot["eligible_count"] == 1
    assert "chave-ficticia-para-teste" not in snapshot_json(snapshot).decode()
