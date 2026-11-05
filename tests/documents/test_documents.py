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


@pytest.mark.parametrize(
    "content,name",
    [
        (b"", "a.txt"),
        (b"x" * (MAX_BYTES + 1), "a.txt"),
        (b"bad", "a.exe"),
        (b"\xff", "a.txt"),
        (b"bad", "a.pdf"),
        (b" ", "a.txt"),
        (b"x" * 25001, "a.txt"),
    ],
)
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
        message = "sem texto selecionável" if pages == 1 and not encrypted else "sem senha, com até cinco páginas"
        with pytest.raises(ValueError, match=message):
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
