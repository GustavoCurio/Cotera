"""Integração HTTP para cestas, extração, comparação e decisão versionada."""

import hmac
import os
from functools import lru_cache
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from .documents import MAX_BYTES
from .extraction import ProviderError
from .models import Decision, PurchaseRequest
from .reports import report_html
from .service import add_document
from .store import ConflictError, Store


def authorize(x_cotera_key: str = Header(default="")) -> None:
    """Exige X-Cotera-Key quando COTERA_API_KEY está configurada no servidor."""
    expected = os.environ.get("COTERA_API_KEY", "")
    if expected and not hmac.compare_digest(x_cotera_key.encode(), expected.encode()):
        raise HTTPException(401, "Chave da API inválida ou ausente.")


app = FastAPI(
    title="Cotera API",
    version="1.0.0",
    dependencies=[Depends(authorize)],
    description="Comparação de propostas comerciais, evidências e decisão humana.",
)


@lru_cache(maxsize=1)
def store() -> Store:
    """Inicializa o armazenamento configurado no primeiro acesso da API."""
    return Store()


@app.get("/health", response_model=None)
def health() -> dict[str, str]:
    """Indica disponibilidade sem abrir banco ou chamar o provedor de IA."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/requests", response_model=None)
def list_requests() -> list[dict[str, Any]]:
    """Lista cestas persistidas no ambiente configurado."""
    return store().list()


@app.post("/requests", status_code=201, response_model=None)
def create_request(body: PurchaseRequest) -> dict[str, Any]:
    """Cria uma cesta após validar códigos, unidades e quantidades."""
    return store().create(body)


@app.get("/requests/{identifier}", response_model=None)
def get_request(identifier: str) -> dict[str, Any]:
    """Devolve comparação recalculada, documentos e decisões; 404 para cesta ausente."""
    try:
        return store().get(identifier)
    except KeyError as error:
        raise HTTPException(404, "Cotação não encontrada.") from error


@app.post("/requests/{identifier}/proposals", response_model=None)
async def add_proposal(
    identifier: str,
    file: UploadFile = File(...),
    mode: Literal["local", "ai"] = Form("local"),
    approve_external_processing: bool = Form(False),
) -> dict[str, Any]:
    """Recebe PDF/TXT, extrai, verifica origem e persiste; reenvio não duplica proposta.

    Retorna 403 sem consentimento de IA, 422 para documento inválido e 502 para
    falha do provedor. Fecha o upload inclusive quando a leitura é recusada.
    """
    try:
        if mode == "ai" and not approve_external_processing:
            raise HTTPException(403, "A extração com IA exige autorização para enviar o texto ao provedor.")
        return add_document(
            store(),
            identifier,
            await file.read(MAX_BYTES + 1),
            file.filename or "",
            mode,
            consent=approve_external_processing,
        )
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


@app.post("/requests/{identifier}/decisions", status_code=201, response_model=None)
def decide(identifier: str, body: Decision) -> dict[str, Any]:
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
def report(identifier: str) -> HTMLResponse:
    """Exporta relatório HTML com valores escapados e histórico de escolhas."""
    return HTMLResponse(report_html(get_request(identifier)).decode("utf-8"))
