"""OCR real sem API; falhas e orçamento são exercitados também sem Tesseract."""

from io import BytesIO
import json
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from streamlit.testing.v1 import AppTest

from cotera import api, documents, ocr
from cotera.comparison import audit_quote
from cotera.demo import DATA, demo_request
from cotera.documents import extract_template, read_document, verify_evidence
from cotera.models import Decision
from cotera.reports import comparison_csv, report_html, snapshot_json
from cotera.service import add_document
from cotera.store import Store
from scripts.create_scanned_samples import generate, generate_evaluation

SCANNED = DATA / "scanned"


def pdf_bytes(*paths, blank=False):
    writer = PdfWriter()
    for path in paths:
        writer.append(PdfReader(path))
    if blank:
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.slow
def test_scanned_fixtures_are_image_only_and_reproducible(tmp_path):
    generate(tmp_path)
    first = {p.name: p.read_bytes() for p in tmp_path.glob("*.pdf")}
    generate(tmp_path)
    assert len(first) == 3
    for path in tmp_path.glob("*.pdf"):
        assert path.read_bytes() == first[path.name] == (SCANNED / path.name).read_bytes()
        assert path.stat().st_size < documents.MAX_BYTES
        assert all(not p.extract_text().strip() for p in PdfReader(path).pages)
    evaluation = tmp_path / "evaluation"
    generate_evaluation(tmp_path, evaluation)
    for path in evaluation.iterdir():
        assert path.read_bytes() == (DATA.parent / "evals" / "llm" / "scanned" / path.name).read_bytes()


@pytest.mark.ocr
@pytest.mark.slow
@pytest.mark.parametrize(
    "name,supplier,total",
    [
        ("aurora_escaneada.pdf", "Aurora Suprimentos", "1405.00"),
        ("prumo_ruido_rotacao.pdf", "Prumo Distribuidora", "1320.00"),
    ],
)
def test_ocr_local_parser_persistence_evidence_and_human_review(require_ocr, tmp_path, name, supplier, total):
    path = SCANNED / name
    store = Store("sqlite:///" + str(tmp_path / "quotes.sqlite3"))
    identifier = store.create(demo_request())["id"]
    result = add_document(store, identifier, path.read_bytes(), path.name)
    snapshot = Store(store.url).get(identifier)
    proposal = snapshot["proposals"][0]
    document = read_document(path.read_bytes(), path.name)
    draft = extract_template(document)
    verify_evidence(draft, document)
    with pytest.raises(ValueError, match="correspondência"):
        verify_evidence(draft.model_copy(update={"freight": 999}), document)
    assert draft.supplier == supplier
    assert len(draft.items) == 3
    assert proposal["extraction"]["mode"] == "local"
    assert proposal["audit"]["computed_total"] == total
    assert proposal["audit"]["eligible"] and proposal["audit"]["requires_human_review"]
    assert "OCR" in proposal["audit"]["warnings"][0]
    page = proposal["document"]["pages"][0]
    assert page["method"] == "ocr" and page["page"] == 1
    assert 0 <= page["ocr_confidence"] <= 100
    assert page["start_line"] == 1 and page["end_line"] == len(document.lines)
    assert document.lines[draft.evidence.reported_total - 1].startswith("Total declarado:")
    assert all("|" in document.lines[item.source_line - 1] for item in draft.items)
    assert json.loads(snapshot_json(snapshot))["proposals"][0]["document"]["pages"] == [page]
    assert "OCR" in report_html(snapshot).decode() and "OCR" in comparison_csv(snapshot).decode("utf-8-sig")
    decision = Decision(
        proposal_id=result["id"],
        expected_version=snapshot["version"],
        actor="Revisor local",
        reason="Valores conferidos no documento original e prazo aceito.",
    )
    with pytest.raises(ValueError, match="revisão humana"):
        store.decide(identifier, decision)
    assert store.get(identifier)["version"] == snapshot["version"]
    decision.ocr_reviewed = True
    assert store.decide(identifier, decision)["ocr_reviewed"] is True


@pytest.mark.ocr
@pytest.mark.slow
def test_scanned_blank_remains_rejected(require_ocr):
    path = SCANNED / "branco_escaneado.pdf"
    with pytest.raises(ValueError, match="sem texto selecionável"):
        read_document(path.read_bytes(), path.name)


def test_native_pdf_does_not_call_ocr_and_old_documents_still_compare(monkeypatch):
    def forbidden(*args):
        pytest.fail("PDF textual não deve chamar OCR.")

    monkeypatch.setattr(documents, "read_scanned_pages", forbidden)
    path = DATA / "proposals" / "aurora.pdf"
    doc = read_document(path.read_bytes(), path.name)
    assert doc.pages[0].method == "texto" and doc.pages[0].ocr_confidence is None
    assert not audit_quote(demo_request(), extract_template(doc), doc)["requires_human_review"]
    legacy = doc.to_dict()
    legacy.pop("pages")
    assert not audit_quote(demo_request(), extract_template(doc), legacy)["requires_human_review"]


@pytest.mark.ocr
@pytest.mark.slow
def test_mixed_pdf_only_scanned_page_uses_ocr_and_lines_remain_global(require_ocr, monkeypatch):
    indexes_seen = []
    original = documents.read_scanned_pages

    def observe(content, indexes):
        indexes_seen.extend(indexes)
        return original(content, indexes)

    monkeypatch.setattr(documents, "read_scanned_pages", observe)
    content = pdf_bytes(DATA / "proposals" / "aurora.pdf", SCANNED / "prumo_ruido_rotacao.pdf", blank=True)
    doc = read_document(content, "misto.pdf")
    assert indexes_seen == [1]
    first, second, third = doc.pages
    assert [p.method for p in doc.pages] == ["texto", "ocr", "texto"]
    assert first.start_line == 1 and second.start_line == first.end_line + 1
    assert second.end_line == len(doc.lines)
    assert third.start_line is third.end_line is None
    assert "Prumo" in "\n".join(doc.lines[second.start_line - 1 : second.end_line])


@pytest.mark.ocr
@pytest.mark.slow
def test_sparse_native_header_still_triggers_ocr(require_ocr):
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(10, 820, "COTERA")
    canvas.save()
    writer = PdfWriter(clone_from=SCANNED / "aurora_escaneada.pdf")
    writer.pages[0].merge_page(PdfReader(buffer).pages[0])
    output = BytesIO()
    writer.write(output)
    doc = read_document(output.getvalue(), "cabecalho.pdf")
    assert doc.pages[0].method == "ocr"
    assert extract_template(doc).supplier == "Aurora Suprimentos"


def test_missing_tesseract_degrades_to_clear_rejection(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "/tesseract-ausente/cotera")
    path = SCANNED / "aurora_escaneada.pdf"
    with pytest.raises(ValueError, match="sem texto selecionável.*Tesseract"):
        read_document(path.read_bytes(), path.name)
    # A falta do executável não prejudica o caminho textual.
    textual = DATA / "proposals" / "aurora.pdf"
    assert read_document(textual.read_bytes(), textual.name).pages[0].method == "texto"


@pytest.mark.parametrize("module", ["pytesseract", "pypdfium2"])
def test_missing_python_ocr_dependency_degrades_to_clear_rejection(monkeypatch, module):
    monkeypatch.setitem(sys.modules, module, None)
    path = SCANNED / "aurora_escaneada.pdf"
    with pytest.raises(ValueError, match="sem texto selecionável.*OCR local indisponível"):
        read_document(path.read_bytes(), path.name)


def test_missing_portuguese_cannot_silently_use_only_english(monkeypatch):
    pytest.importorskip("pytesseract")
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="eng\n"))
    path = SCANNED / "aurora_escaneada.pdf"
    with pytest.raises(ValueError, match="sem texto selecionável.*por\\+eng"):
        read_document(path.read_bytes(), path.name)


@pytest.mark.parametrize("setting", ["0", "-1", "nan", "inf", "inválido"])
def test_invalid_ocr_budget_is_rejected(monkeypatch, setting):
    monkeypatch.setenv("COTERA_OCR_TIMEOUT_SECONDS", setting)
    with pytest.raises(ValueError, match="positivo finito"):
        ocr.read_scanned_pages(b"", [0])


def test_total_ocr_timeout_is_shared_between_pages(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    pytest.importorskip("pypdfium2")
    elapsed, timeouts = [0.0], []
    monkeypatch.setenv("COTERA_OCR_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(ocr, "monotonic", lambda: elapsed[0])

    def probe(*args, **kwargs):
        elapsed[0] += 0.5
        return subprocess.CompletedProcess(args, 0, stdout="por\neng\n")

    monkeypatch.setattr(ocr.subprocess, "run", probe)

    def recognize(*args, timeout, **kwargs):
        timeouts.append(timeout)
        if len(timeouts) == 2:
            raise RuntimeError("Tesseract process timeout")
        elapsed[0] += 2
        return "level\tblock_num\tpar_num\tline_num\tconf\ttext\n5\t1\t1\t1\t90\tCotera\n"

    monkeypatch.setattr(pytesseract.pytesseract, "run_and_get_output", recognize)
    path = SCANNED / "aurora_escaneada.pdf"
    content = pdf_bytes(path, path)
    with pytest.raises(ValueError, match="Tempo total de OCR excedido"):
        read_document(content, "duas.pdf")
    assert timeouts == [2.5, 0.5]


def test_ocr_never_bypasses_existing_document_limits(monkeypatch):
    def forbidden(*args):
        pytest.fail("Limites precisam ser aplicados antes do OCR.")

    monkeypatch.setattr(documents, "read_scanned_pages", forbidden)
    path = SCANNED / "aurora_escaneada.pdf"
    with pytest.raises(ValueError, match="até cinco páginas"):
        read_document(pdf_bytes(*([path] * 6)), "seis.pdf")
    with pytest.raises(ValueError, match="até 2 MB"):
        read_document(b"x" * (documents.MAX_BYTES + 1), "grande.pdf")


@pytest.mark.parametrize("text", ["a" * 25_001, "a\n" * 1001, "a" * 2001])
def test_ocr_output_obeys_the_same_text_limits(monkeypatch, text):
    monkeypatch.setattr(documents, "read_scanned_pages", lambda *args: {0: (text, 90.0)})
    path = SCANNED / "aurora_escaneada.pdf"
    with pytest.raises(ValueError, match="acima dos limites de leitura"):
        read_document(path.read_bytes(), path.name)


@pytest.mark.ocr
@pytest.mark.slow
def test_scanned_baseline_uses_ocr_without_constructing_openai(require_ocr, tmp_path, monkeypatch):
    from evals import run_llm_eval as runner

    def forbidden(*args, **kwargs):
        pytest.fail("Baseline OCR não pode construir cliente de API.")

    monkeypatch.setattr("openai.OpenAI", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", "ficticia-nao-usar")
    output = tmp_path / "baseline.json"
    manifest = DATA.parent / "evals" / "llm" / "scanned" / "manifest.json"
    assert runner.main(["--baseline-only", "--manifest", str(manifest), "--output", str(output)]) == 0
    report = json.loads(output.read_text("utf-8"))
    assert report["llm"]["status"] == "not_run" and report["llm"]["runs"] == []
    assert report["baseline"]["metrics"]["accepted"]["correct"] == 2
    assert report["baseline"]["metrics"]["total_correctness"]["correct"] == 2
    for case in report["baseline"]["documents"]:
        assert case["document_pages"][0]["method"] == "ocr"
        assert case["observed_audit"]["requires_human_review"]


@pytest.mark.ocr
@pytest.mark.slow
def test_api_ocr_requires_review_before_decision(require_ocr, tmp_path, monkeypatch):
    store = Store("sqlite:///" + str(tmp_path / "api.sqlite3"))
    monkeypatch.setattr(api, "store", lambda: store)
    monkeypatch.delenv("COTERA_API_KEY", raising=False)
    with TestClient(api.app) as client:
        identifier = client.post("/requests", json=demo_request().model_dump(mode="json")).json()["id"]
        route = f"/requests/{identifier}"
        path = SCANNED / "aurora_escaneada.pdf"
        assert client.post(route + "/proposals", files={"file": (path.name, path.read_bytes())}).status_code == 200
        snapshot = client.get(route).json()
        body = dict(
            proposal_id=snapshot["proposals"][0]["id"],
            expected_version=snapshot["version"],
            actor="Revisor",
            reason="Conferência dos valores no PDF original concluída.",
        )
        assert client.post(route + "/decisions", json=body).status_code == 422
        assert client.post(route + "/decisions", json={**body, "ocr_reviewed": True}).status_code == 201


@pytest.mark.ocr
@pytest.mark.slow
def test_streamlit_scanned_example_confidence_and_review(require_ocr, tmp_path, monkeypatch):
    monkeypatch.setenv("COTERA_DEMO_HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ui = AppTest.from_file(str(DATA.parent / "app.py"), default_timeout=60).run()
    next(b for b in ui.button if b.label == "Carregar exemplo escaneado").click().run()
    assert not ui.exception and ui.segmented_control[0].value == "Documentos"
    snapshot = Store("sqlite:///" + str(tmp_path / "demo.sqlite3")).get(ui.selectbox(key="cotera_purchase").value)
    scanned = next(p for p in snapshot["proposals"] if p["audit"]["requires_human_review"])
    next(s for s in ui.selectbox if s.label == "Documento em conferência").set_value(scanned["id"]).run()
    assert any("Texto obtido por OCR" in w.value and "confiança média" in w.value for w in ui.warning)
    ui.segmented_control[0].set_value("Comparar").run()
    assert not ui.exception and any("Texto obtido por OCR" in w.value for w in ui.warning)
    next(s for s in ui.selectbox if s.label == "Proposta escolhida").set_value(scanned["id"])
    next(t for t in ui.text_input if t.label == "Responsável pela escolha").set_value("Revisor")
    next(t for t in ui.text_area if t.label == "Justificativa").set_value(
        "Valores e prazo conferidos no documento original."
    )
    next(b for b in ui.button if b.label == "Registrar decisão").click().run()
    assert any("revisão humana" in e.value for e in ui.error)
    next(c for c in ui.checkbox if c.label.startswith("Revisei no PDF")).check()
    next(b for b in ui.button if b.label == "Registrar decisão").click().run()
    assert not ui.exception and ui.success
