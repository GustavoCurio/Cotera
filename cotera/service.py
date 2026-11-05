"""Fluxo compartilhado pela interface e API, com deduplicação antes da chamada externa."""
from .documents import read_document
from .extraction import extract
from .models import PurchaseRequest


def add_document(store, identifier, content, filename, mode="local", *, consent=False, client=None, model=None, api_key=None):
    """Lê, extrai e registra uma proposta sem repetir processamento de bytes já recebidos.

    A autorização de IA é verificada mesmo em reenvios. A inserção transacional
    ainda repete a deduplicação para cobrir envios concorrentes.
    """
    if mode not in {"local", "ai"}:
        raise ValueError("Modo de extração inválido.")
    if mode == "ai" and not consent:
        raise PermissionError("Autorize o envio do texto ao provedor para usar a extração com IA.")
    snapshot = store.get(identifier)
    document = read_document(content, filename)
    existing = next((p for p in snapshot["proposals"] if p["document"]["sha256"] == document.sha256), None)
    if existing:
        return {"id": existing["id"], "created": False}
    if len(snapshot["proposals"]) >= 10:
        raise ValueError("Limite de dez propostas por cotação atingido.")
    draft, metadata = extract(document, PurchaseRequest.model_validate(snapshot["request"]), mode,
                              consent=consent, client=client, model=model, api_key=api_key)
    return store.add_proposal(identifier, document, draft, metadata)
