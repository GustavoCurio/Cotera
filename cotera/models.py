"""Contratos de compra, extração e decisão; valores monetários usam Decimal."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[Decimal, Field(ge=0, le=Decimal("100000000"), max_digits=14, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), max_digits=12, decimal_places=3)]
Code = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,23}$")]


class Contract(BaseModel):
    """Recusa campos extras e remove espaços nas extremidades de textos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class RequestItem(Contract):
    """Item da cesta de referência; a unidade deve coincidir exatamente na proposta."""

    sku: Code
    description: str = Field(min_length=2, max_length=120)
    quantity: Quantity
    unit: Literal["un", "kg", "m", "l", "h"] = "un"


class PurchaseRequest(Contract):
    """Cesta imutável e prazo máximo opcional, contado em dias corridos declarados."""

    title: str = Field(min_length=3, max_length=120)
    items: list[RequestItem] = Field(min_length=1, max_length=20)
    max_delivery_days: int | None = Field(default=None, ge=0, le=365)

    @model_validator(mode="after")
    def unique_skus(self):
        """Garante que cada código representa um único item da cesta."""
        if len({item.sku for item in self.items}) != len(self.items):
            raise ValueError("A cesta contém códigos de item repetidos.")
        return self


class QuoteItem(Contract):
    """Linha extraída; None representa informação ausente, nunca preço zero implícito."""

    sku: Code | None = None
    quantity: Quantity | None = None
    unit: str | None = Field(default=None, max_length=20)
    unit_price: Amount | None = None
    source_line: int = Field(ge=1, le=1000)


class Evidence(Contract):
    """Posições de base um no texto extraído, também reproduzido na interface."""

    supplier: int | None = None
    reference: int | None = None
    currency: int | None = None
    delivery_days: int | None = None
    freight: int | None = None
    discount: int | None = None
    reported_total: int | None = None


class QuoteDraft(Contract):
    """Saída da extração, anterior à avaliação de completude e dos cálculos."""

    supplier: str | None = Field(default=None, min_length=2, max_length=120)
    reference: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    delivery_days: int | None = Field(default=None, ge=0, le=365)
    freight: Amount | None = None
    discount: Amount | None = None
    reported_total: Amount | None = None
    items: list[QuoteItem] = Field(default_factory=list, max_length=40)
    evidence: Evidence = Field(default_factory=Evidence)


class Decision(Contract):
    """Escolha justificada vinculada à versão do conjunto comparado."""

    proposal_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=15, max_length=1500)
    ocr_reviewed: bool = False
