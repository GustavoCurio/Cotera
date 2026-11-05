"""Leitura limitada de PDF/TXT com OCR local e parser do modelo Cotera."""

import re
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal

from pypdf import PdfReader

from .models import QuoteDraft
from .ocr import NO_TEXT, read_scanned_pages

MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 5
MAX_CHARS = 25_000
MIN_PAGE_TEXT = 30  # caracteres alfanuméricos; cabeçalhos isolados não bastam.


def br_number(text: str) -> Decimal:
    """Lê número brasileiro explícito, com agrupamento válido e sem notação científica."""
    value = text.strip().removeprefix("R$").strip()
    if not re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,3})?", value):
        raise ValueError("Número fora do formato brasileiro esperado.")
    try:
        return Decimal(value.replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise ValueError("Número inválido.") from error


@dataclass(frozen=True)
class PageProvenance:
    """Página de base um e intervalo inclusivo na numeração global de evidências."""

    page: int
    method: Literal["texto", "ocr"]
    ocr_confidence: float | None = None  # média das palavras, na escala 0–100.
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class Document:
    """Texto por linhas e hash dos bytes originais; nenhum PDF é persistido."""

    filename: str
    sha256: str
    lines: list[str]
    pages: list[PageProvenance] = dataclass_field(default_factory=list)

    def to_dict(self):
        """Serializa a evidência mantida junto da proposta."""
        return asdict(self)


def read_document(content: bytes, filename: str) -> Document:
    """Lê até 2 MiB/cinco páginas; tenta OCR local em páginas com texto insuficiente."""
    name = Path(filename.replace("\\", "/")).name[:120]
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Envie um arquivo não vazio de até 2 MB.")
    suffix = Path(name).suffix.lower()
    methods, confidences = [], []
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("O TXT precisa estar em UTF-8.") from error
        fragments = [text]
        methods, confidences = ["texto"], [None]
    elif suffix == ".pdf":
        try:
            pdf = PdfReader(BytesIO(content), strict=True)
            if pdf.is_encrypted or not 1 <= len(pdf.pages) <= MAX_PAGES:
                raise ValueError("Use um PDF sem senha, com até cinco páginas.")
            fragments, scanned = [], []
            for index, page in enumerate(pdf.pages):
                # Limita também o fluxo descomprimido antes do processamento textual.
                stream = page.get_contents()
                data = stream.get_data() if stream is not None else b""
                if len(data) > 2_000_000:
                    raise ValueError("Página PDF com conteúdo excessivo.")
                fragments.append(page.extract_text(extraction_mode="plain") or "")
                # Página estruturalmente vazia não precisa do motor OCR.
                if data.strip() and sum(char.isalnum() for char in fragments[-1]) < MIN_PAGE_TEXT:
                    scanned.append(index)
                if sum(map(len, fragments)) > MAX_CHARS:
                    raise ValueError("O documento excede 25 mil caracteres.")
            methods, confidences = ["texto"] * len(fragments), [None] * len(fragments)
            if scanned:
                for index, (ocr_text, confidence) in read_scanned_pages(content, scanned).items():
                    fragments[index] = ocr_text
                    methods[index], confidences[index] = "ocr", confidence
            text = "\n".join(fragments)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("Não foi possível ler este PDF.") from error
    else:
        raise ValueError("Envie um PDF com texto selecionável ou um TXT.")
    lines, pages = [], []
    for index, fragment in enumerate(fragments):
        start = len(lines) + 1
        page_lines = [line.strip() for line in fragment.splitlines() if line.strip()]
        lines.extend(page_lines)
        pages.append(
            PageProvenance(
                index + 1,
                methods[index],
                confidences[index],
                start if page_lines else None,
                len(lines) if page_lines else None,
            )
        )
    if not lines or len(text) > MAX_CHARS or len(lines) > 1000 or any(len(line) > 2000 for line in lines):
        raise ValueError(NO_TEXT)
    return Document(name, sha256(content).hexdigest(), lines, pages)


ROOT_FIELDS = {
    "Fornecedor": "supplier",
    "Referência": "reference",
    "Moeda": "currency",
    "Prazo": "delivery_days",
    "Frete": "freight",
    "Desconto": "discount",
    "Total declarado": "reported_total",
}
MONEY_FIELDS = {"freight", "discount", "reported_total"}


def extract_template(document: Document) -> QuoteDraft:
    """Interpreta somente o modelo rotulado incluído no projeto; não usa IA."""
    payload = {"items": [], "evidence": {}}
    for number, line in enumerate(document.lines, 1):
        for label, field in ROOT_FIELDS.items():
            if line.startswith(label + ":"):
                if field in payload:
                    raise ValueError(f"Campo repetido no documento: {label}.")
                raw = line.split(":", 1)[1].strip()
                if not raw:
                    continue
                if field in MONEY_FIELDS:
                    value = br_number(raw)
                elif field == "delivery_days":
                    match = re.fullmatch(r"(\d{1,3}) dias?", raw)
                    if not match:
                        raise ValueError("Prazo precisa seguir o modelo: 5 dias.")
                    value = int(match[1])
                else:
                    value = raw
                payload[field] = value
                payload["evidence"][field] = number
        if "|" in line and not line.startswith("SKU"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 4:
                raise ValueError("Linha de item fora do modelo SKU | Quantidade | Unidade | Preço unitário.")
            sku, quantity, unit, price = parts
            payload["items"].append(
                dict(sku=sku, quantity=br_number(quantity), unit=unit, unit_price=br_number(price), source_line=number)
            )
    if not payload["evidence"]:
        raise ValueError("Modelo não reconhecido. Use o exemplo Cotera ou a extração com IA.")
    draft = QuoteDraft.model_validate(payload)
    verify_evidence(draft, document)
    return draft


def verify_evidence(draft: QuoteDraft, document: Document):
    """Exige ocorrência literal de cada valor na linha citada, sem provar sua semântica.

    Números são comparados após leitura no formato brasileiro. A correspondência
    literal não garante que um LLM associou o número à coluna correta.
    """

    def check(value, line, numeric=False):
        if value is None:
            if line is not None:
                raise ValueError("Campo ausente com referência inconsistente.")
            return
        if line is None or not 1 <= line <= len(document.lines):
            raise ValueError("Referência de origem inexistente.")
        text = document.lines[line - 1]
        if numeric:
            tokens = re.findall(r"(?<![\w-])-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,3})?(?!\w)", text)
            found = any(br_number(token) == Decimal(str(value)) for token in tokens)
        else:
            found = re.search(r"(?<!\w)" + re.escape(str(value)) + r"(?!\w)", text, re.I) is not None
        if not found:
            raise ValueError("Valor extraído sem correspondência na linha informada.")

    for field in ROOT_FIELDS.values():
        # R$ é indicação explícita de BRL, embora o código não esteja escrito.
        if (
            field == "currency"
            and draft.currency == "BRL"
            and draft.evidence.currency is not None
            and 1 <= draft.evidence.currency <= len(document.lines)
            and "R$" in document.lines[draft.evidence.currency - 1]
        ):
            continue
        check(getattr(draft, field), getattr(draft.evidence, field), field in MONEY_FIELDS or field == "delivery_days")
    for item in draft.items:
        for field in ["sku", "quantity", "unit", "unit_price"]:
            value = getattr(item, field)
            if value is not None:
                check(value, item.source_line, field in {"quantity", "unit_price"})
