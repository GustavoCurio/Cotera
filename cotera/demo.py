"""Cesta e propostas de fornecedores fictícios para explorar o Cotera."""

from pathlib import Path
from hashlib import sha256
from .documents import read_document
from .extraction import extract
from .models import PurchaseRequest

DATA = Path(__file__).resolve().parents[1] / "data"
DEMO_TITLE = "Reposição do escritório · demonstração"


def demo_request():
    """Cesta fixa de vinte resmas, cinquenta canetas e dez organizadores."""
    return PurchaseRequest(
        title=DEMO_TITLE,
        items=[
            {"sku": "PAP-A4", "description": "Papel A4 · resma de 500 folhas", "quantity": "20", "unit": "un"},
            {"sku": "CAN-AZ", "description": "Caneta esferográfica azul", "quantity": "50", "unit": "un"},
            {"sku": "ORG-M", "description": "Organizador de mesa", "quantity": "10", "unit": "un"},
        ],
    )


def seed_demo(store, *, scanned=False):
    """Cria a demonstração uma vez; reenvios dos PDFs são deduplicados pelo hash."""
    request = demo_request()
    if scanned:
        request.title = DEMO_TITLE + " escaneada"
    existing = next((row for row in store.list() if row["title"] == request.title), None)
    identifier = existing["id"] if existing else store.create(request)["id"]
    hashes = {p["document"]["sha256"] for p in store.get(identifier)["proposals"]}
    for original in sorted((DATA / "proposals").glob("*.pdf")):
        path = DATA / "scanned" / "aurora_escaneada.pdf" if scanned and original.stem == "aurora" else original
        content = path.read_bytes()
        if sha256(content).hexdigest() in hashes:
            continue
        document = read_document(content, path.name)
        draft, metadata = extract(document, request)
        store.add_proposal(identifier, document, draft, metadata)
    return identifier
