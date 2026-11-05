"""Avaliação reproduzível do parser local e das regras, em conjunto sintético explícito."""

import json

from .comparison import audit_quote
from .demo import DATA, demo_request
from .documents import extract_template, read_document


def evaluate():
    """Compara elegibilidade e total calculado com oito expectativas fixas; não mede LLM."""
    cases = json.loads((DATA.parent / "evals" / "cases.json").read_text("utf-8"))
    results = []
    for case in cases:
        draft = extract_template(read_document(case["text"].encode("utf-8"), case["name"] + ".txt"))
        audit = audit_quote(demo_request(), draft)
        results.append(
            {
                "case": case["name"],
                "expected_eligible": case["eligible"],
                "observed_eligible": audit["eligible"],
                "expected_total": case["total"],
                "observed_total": audit["computed_total"],
                "passed": audit["eligible"] == case["eligible"] and audit["computed_total"] == case["total"],
            }
        )
    return {
        "method": "parser local e regras; casos sintéticos de desenvolvimento; sem chamada a LLM",
        "cases": results,
        "passed": sum(case["passed"] for case in results),
        "total": len(results),
    }
