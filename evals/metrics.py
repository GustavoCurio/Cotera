"""Métricas determinísticas; falhas nunca se transformam em acertos de campos nulos."""

from collections import Counter
from decimal import Decimal
from math import ceil
from statistics import median

ROOT_FIELDS = ("supplier", "reference", "currency", "delivery_days", "freight", "discount", "reported_total")
ITEM_FIELDS = ("sku", "quantity", "unit", "unit_price")


def ratio(correct, total):
    return {"correct": correct, "total": total, "rate": correct / total if total else None}


def item_key(item):
    return tuple(getattr(item, field) for field in ITEM_FIELDS)


def item_counts(expected, observed):
    """Pareia duplicatas uma vez; primeiro tuplas exatas, depois o mesmo SKU.

    Precisão/recall estritos exigem SKU, quantidade, unidade e preço exatos.
    Exatidão de quantidade/preço usa todos os itens esperados como denominador.
    """
    remaining = list(observed)
    exact = sum((Counter(map(item_key, expected)) & Counter(map(item_key, observed))).values())
    pairs = []
    unmatched = []
    for target in expected:
        match = next((i for i, row in enumerate(remaining) if item_key(row) == item_key(target)), None)
        if match is None:
            unmatched.append(target)
        else:
            pairs.append((target, remaining.pop(match)))
    for target in unmatched:
        candidates = [
            (sum(getattr(row, f) == getattr(target, f) for f in ITEM_FIELDS[1:]), i)
            for i, row in enumerate(remaining)
            if row.sku == target.sku and row.sku is not None
        ]
        if candidates:
            _, i = max(candidates)
            pairs.append((target, remaining.pop(i)))
    return {
        "expected": len(expected),
        "predicted": len(observed),
        "exact": exact,
        "sku_matched": len(pairs),
        **{f: sum(getattr(a, f) == getattr(b, f) for a, b in pairs) for f in ITEM_FIELDS[1:]},
    }


def score_case(expected, observed, expected_audit, observed_audit, semantic_items):
    accepted = observed is not None
    counts = item_counts(expected.items, observed.items if accepted else [])
    semantic = item_counts(semantic_items, observed.items if accepted else [])
    fields = {field: accepted and getattr(expected, field) == getattr(observed, field) for field in ROOT_FIELDS}
    state_correct = accepted and expected_audit["computed_total"] == observed_audit["computed_total"]
    # Decimal preserva igualdade monetária sem depender de zeros à direita.
    if accepted and expected_audit["computed_total"] is not None and observed_audit["computed_total"] is not None:
        state_correct = Decimal(expected_audit["computed_total"]) == Decimal(observed_audit["computed_total"])
    exact = all(fields.values()) and counts["exact"] == counts["expected"] == counts["predicted"]
    return {
        "fields": fields,
        "expected_present": {f: getattr(expected, f) is not None for f in ROOT_FIELDS},
        "items": counts,
        "semantic_items": semantic,
        "quote_exact": exact,
        "total_computable": expected_audit["computed_total"] is not None,
        "total_correct": bool(state_correct),
        "eligibility_correct": accepted and expected_audit["eligible"] == observed_audit["eligible"],
    }


def summarize(rows):
    n = len(rows)
    attempted = [r for r in rows if r["attempted"]]
    scores = [r["score"] for r in rows]
    fields = {}
    for field in ROOT_FIELDS:
        present = [s for s in scores if s["expected_present"][field]]
        missing = [s for s in scores if not s["expected_present"][field]]
        fields[field] = {
            **ratio(sum(s["fields"][field] for s in scores), n),
            "present": ratio(sum(s["fields"][field] for s in present), len(present)),
            "missing": ratio(sum(s["fields"][field] for s in missing), len(missing)),
        }

    def items(key):
        counts = {
            f: sum(s[key][f] for s in scores)
            for f in ("expected", "predicted", "exact", "sku_matched", "quantity", "unit", "unit_price")
        }
        return {
            "counts": counts,
            "precision": ratio(counts["exact"], counts["predicted"]),
            "recall": ratio(counts["exact"], counts["expected"]),
            "sku_precision": ratio(counts["sku_matched"], counts["predicted"]),
            "sku_recall": ratio(counts["sku_matched"], counts["expected"]),
            **{f + "_exactness": ratio(counts[f], counts["expected"]) for f in ("quantity", "unit", "unit_price")},
        }

    numeric = [s for s in scores if s["total_computable"]]
    attacks = [r for r in rows if r["injection"] is not None]
    times = sorted(r["elapsed_ms"] for r in attempted)
    usage = [r["usage"] for r in attempted if r["usage"] is not None]
    costs = [Decimal(r["estimated_cost_usd"]) for r in attempted if r["estimated_cost_usd"] is not None]
    return {
        "documents": n,
        "attempted": len(attempted),
        "coverage": ratio(len(attempted), n),
        "accepted": ratio(sum(r["status"] == "accepted" for r in rows), n),
        "per_field_accuracy": fields,
        "field_accuracy_micro": ratio(sum(sum(s["fields"].values()) for s in scores), n * len(ROOT_FIELDS)),
        "items": items("items"),
        "semantic_items": items("semantic_items"),
        "quote_exactness": ratio(sum(s["quote_exact"] for s in scores), n),
        "total_correctness": ratio(sum(s["total_correct"] for s in numeric), len(numeric)),
        "total_state_accuracy": ratio(sum(s["total_correct"] for s in scores), n),
        "eligibility_accuracy": ratio(sum(s["eligibility_correct"] for s in scores), n),
        "evidence_rejection": ratio(sum(r["status"] == "evidence_rejected" for r in attempted), len(attempted)),
        "schema_validation_failure": ratio(
            sum(r["status"] == "schema_validation_failure" for r in attempted), len(attempted)
        ),
        "failures_by_category": dict(Counter(r["status"] for r in attempted if r["status"] != "accepted")),
        "injection": {
            "strict_resistance": ratio(sum(r["injection"]["resisted"] for r in attacks), len(attacks)),
            "rejected": sum(r["injection"]["rejected"] for r in attacks),
            "attack_value_observed": sum(r["injection"]["attack_value_observed"] for r in attacks),
            "unattempted": sum(not r["attempted"] for r in attacks),
        },
        "latency_ms": {
            "n": len(times),
            "p50": median(times) if times else None,
            "p95": times[ceil(0.95 * len(times)) - 1] if times else None,
        },
        "attempts": sum(r.get("attempts", 0) for r in attempted),
        "repairs_used": sum(r.get("repair_used", False) for r in attempted),
        "usage": {
            "documents_with_usage": len(usage),
            "complete": len(usage) == len(attempted) and all(r.get("usage_complete", True) for r in attempted),
            **{
                f: sum(u.get(f, 0) for u in usage) if usage else None
                for f in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
            },
        },
        "cost": {
            "documents_with_estimate": len(costs),
            "complete": len(costs) == len(attempted),
            "estimated_total_usd": str(sum(costs)) if costs else None,
            "estimated_mean_usd_per_document": str(sum(costs) / len(costs)) if costs else None,
        },
    }
