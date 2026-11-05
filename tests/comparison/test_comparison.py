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


def test_round_half_up_and_unit_and_deadline(document):
    request = PurchaseRequest(
        title="Uma unidade", items=[{"sku": "AB", "description": "Item fracionável", "quantity": "0.125", "unit": "kg"}]
    )
    draft = QuoteDraft(
        supplier="Teste",
        reference="01",
        currency="BRL",
        delivery_days=5,
        freight="0",
        discount="0",
        reported_total="0.13",
        items=[{"sku": "AB", "quantity": "0.125", "unit": "kg", "unit_price": "1", "source_line": 1}],
    )
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
    copied["id"] = "f" * 32
    tied = compare(demo_request(), [lowest, copied])
    assert len(tied["lowest_cost_ids"]) == 2


def test_exports_escape_html_and_neutralize_formulas(store):
    snapshot = store.get(seed_demo(store))
    snapshot["request"]["title"] = "<script>alert(1)</script>"
    snapshot["proposals"][0]["draft"]["supplier"] = "=HYPERLINK(1)"
    html = report_html(snapshot).decode()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "'=HYPERLINK(1)" in comparison_csv(snapshot).decode("utf-8-sig")
    assert json.loads(snapshot_json(snapshot))["request"]["title"] == snapshot["request"]["title"]
