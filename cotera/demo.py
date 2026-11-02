"""Cesta e propostas de fornecedores fictícios para explorar o Cotera."""
from pathlib import Path
from .documents import read_document
from .extraction import extract
from .models import PurchaseRequest

DATA = Path(__file__).resolve().parents[1] / "data"
DEMO_TITLE = "Reposição do escritório · demonstração"


def demo_request():
    """Cesta fixa de vinte resmas, cinquenta canetas e dez organizadores."""
    return PurchaseRequest(title=DEMO_TITLE, items=[
        {"sku": "PAP-A4", "description": "Papel A4 · resma de 500 folhas", "quantity": "20", "unit": "un"},
        {"sku": "CAN-AZ", "description": "Caneta esferográfica azul", "quantity": "50", "unit": "un"},
        {"sku": "ORG-M", "description": "Organizador de mesa", "quantity": "10", "unit": "un"},
    ])


def seed_demo(store):
    """Cria a demonstração uma vez; reenvios dos PDFs são deduplicados pelo hash."""
    request = demo_request()
    existing = next((row for row in store.list() if row["title"] == DEMO_TITLE), None)
    identifier = existing["id"] if existing else store.create(request)["id"]
    for path in sorted((DATA / "proposals").glob("*.pdf")):
        document = read_document(path.read_bytes(), path.name)
        draft, metadata = extract(document, request)
        store.add_proposal(identifier, document, draft, metadata)
    return identifier
