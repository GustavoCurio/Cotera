"""Integração HTTP para cestas, extração, comparação e decisão versionada."""
from functools import lru_cache
import hmac
import os
from typing import Literal
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from .documents import MAX_BYTES, read_document
from .extraction import ProviderError, extract
from .models import Decision, PurchaseRequest
from .reports import report_html
from .store import ConflictError, Store
from .service import add_document


def authorize(x_cotera_key: str = Header(default="")):
    """Exige X-Cotera-Key quando COTERA_API_KEY está configurada no servidor."""
    expected = os.environ.get("COTERA_API_KEY", "")
    if expected and not hmac.compare_digest(x_cotera_key.encode(), expected.encode()):
        raise HTTPException(401, "Chave da API inválida ou ausente.")


app = FastAPI(title="Cotera API", version="1.0.0", dependencies=[Depends(authorize)],
              description="Comparação de propostas comerciais, evidências e decisão humana.")


@lru_cache(maxsize=1)
def store():
    """Inicializa o armazenamento configurado no primeiro acesso da API."""
    return Store()


@app.get("/health")
def health():
    """Indica disponibilidade sem abrir banco ou chamar o provedor de IA."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/requests")
def list_requests():
    """Lista cestas persistidas no ambiente configurado."""
    return store().list()


@app.post("/requests", status_code=201)
def create_request(body: PurchaseRequest):
    """Cria uma cesta após validar códigos, unidades e quantidades."""
    return store().create(body)


@app.get("/requests/{identifier}")
def get_request(identifier: str):
    """Devolve comparação recalculada, documentos e decisões; 404 para cesta ausente."""
    try:
        return store().get(identifier)
    except KeyError as error:
        raise HTTPException(404, "Cotação não encontrada.") from error


@app.post("/requests/{identifier}/proposals")
async def add_proposal(identifier: str, file: UploadFile = File(...), mode: Literal["local", "ai"] = Form("local"),
                       approve_external_processing: bool = Form(False)):
    """Recebe PDF/TXT, extrai, verifica origem e persiste; reenvio não duplica proposta.

    Retorna 403 sem consentimento de IA, 422 para documento inválido e 502 para
    falha do provedor. Fecha o upload inclusive quando a leitura é recusada.
    """
    try:
        if mode == "ai" and not approve_external_processing:
            raise HTTPException(403, "A extração com IA exige autorização para enviar o texto ao provedor.")
        return add_document(store(), identifier, await file.read(MAX_BYTES + 1), file.filename or "", mode, consent=approve_external_processing)
    except KeyError as error:
        raise HTTPException(404, "Cotação não encontrada.") from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    except ProviderError as error:
        raise HTTPException(502, {"code": error.code, "message": str(error), "extraction": error.metadata}) from error
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, "Documento ou valores inválidos. Confira o modelo e os limites de entrada.") from error
    finally:
        await file.close()


@app.post("/requests/{identifier}/decisions", status_code=201)
def decide(identifier: str, body: Decision):
    """Registra a escolha humana; 409 se o conjunto comparado mudou."""
    try:
        return store().decide(identifier, body)
    except KeyError as error:
        raise HTTPException(404, "Cotação não encontrada.") from error
    except ConflictError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/requests/{identifier}/report", response_class=HTMLResponse)
def report(identifier: str):
    """Exporta relatório HTML com valores escapados e histórico de escolhas."""
    return HTMLResponse(report_html(get_request(identifier)).decode("utf-8"))
