"""Cálculos determinísticos para propostas da mesma cesta; IA não escolhe fornecedor."""
from decimal import Decimal, ROUND_HALF_UP
from .models import PurchaseRequest, QuoteDraft


def money(value: Decimal) -> Decimal:
    """Arredonda cada total de linha para centavos, com ROUND_HALF_UP."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def audit_quote(request: PurchaseRequest, quote: QuoteDraft) -> dict:
    """Avalia completude, cesta, unidade, quantidade, prazo e reconciliação do total.

    eligible=True exige que todas as verificações passem. Itens não são
    convertidos entre unidades e nenhuma ausência é preenchida com zero.
    """
    issues, rows = [], []
    expected = {item.sku: item for item in request.items}
    seen = set()
    subtotal = Decimal("0")
    for field, label in [("supplier", "Fornecedor"), ("reference", "Referência"), ("currency", "Moeda"),
                         ("delivery_days", "Prazo"), ("freight", "Frete"), ("discount", "Desconto"), ("reported_total", "Total declarado")]:
        if getattr(quote, field) is None:
            issues.append(f"{label} não informado.")
    if quote.currency is not None and quote.currency != "BRL":
        issues.append("A comparação aceita somente propostas em BRL.")
    for item in quote.items:
        complete = all(getattr(item, field) is not None for field in ["sku", "quantity", "unit", "unit_price"])
        if not complete:
            issues.append(f"Item na linha {item.source_line} incompleto.")
        if item.sku in seen:
            issues.append(f"Item repetido: {item.sku}.")
        seen.add(item.sku)
        target = expected.get(item.sku)
        if target is None:
            issues.append(f"Item fora da cesta: {item.sku or 'sem código'}.")
        elif item.quantity != target.quantity or item.unit != target.unit:
            issues.append(f"Quantidade ou unidade divergente: {item.sku}.")
        total = money(item.quantity * item.unit_price) if item.quantity is not None and item.unit_price is not None else None
        if total is not None:
            subtotal += total
        rows.append({"sku": item.sku, "quantity": str(item.quantity) if item.quantity is not None else None,
                     "unit": item.unit, "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                     "line_total": str(total) if total is not None else None, "source_line": item.source_line})
    for sku in expected.keys() - seen:
        issues.append(f"Item obrigatório ausente: {sku}.")
    computed = money(subtotal + quote.freight - quote.discount) if quote.freight is not None and quote.discount is not None and all(r["line_total"] is not None for r in rows) and rows else None
    if computed is not None and computed < 0:
        issues.append("O desconto resulta em total negativo.")
    if computed is not None and quote.reported_total is not None and computed != quote.reported_total:
        issues.append(f"Total declarado diverge: calculado {computed}; documento {quote.reported_total}.")
    if request.max_delivery_days is not None and quote.delivery_days is not None and quote.delivery_days > request.max_delivery_days:
        issues.append(f"Prazo excede o limite de {request.max_delivery_days} dias.")
    return {"eligible": not issues, "issues": sorted(set(issues)), "items": rows,
            "subtotal": str(money(subtotal)), "computed_total": str(computed) if computed is not None else None}


def compare(request: PurchaseRequest, proposals: list[dict]) -> dict:
    """Ordena elegíveis por custo; empates mantêm todos os fornecedores de menor custo."""
    rows = [{**p, "audit": audit_quote(request, QuoteDraft.model_validate(p["draft"]))} for p in proposals]
    valid = sorted((row for row in rows if row["audit"]["eligible"]), key=lambda p: (Decimal(p["audit"]["computed_total"]), p["id"]))
    best = Decimal(valid[0]["audit"]["computed_total"]) if valid else None
    return {"proposals": rows, "eligible_count": len(valid),
            "lowest_cost_ids": [p["id"] for p in valid if Decimal(p["audit"]["computed_total"]) == best],
            "lowest_cost": str(best) if best is not None else None}
