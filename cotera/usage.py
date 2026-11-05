"""Uso e estimativas em USD; cache e raciocínio são subconjuntos, nunca tokens extras."""

from decimal import Decimal
import json
import os
from pathlib import Path

PRICING_PATH = Path(__file__).with_name("llm_pricing.json")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")


def value(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def usage_from(response):
    usage = value(response, "usage")
    if usage is None:
        return None
    counts = {
        "input_tokens": value(usage, "input_tokens"),
        "output_tokens": value(usage, "output_tokens"),
        "cached_input_tokens": value(value(usage, "input_tokens_details"), "cached_tokens", 0) or 0,
        "reasoning_tokens": value(value(usage, "output_tokens_details"), "reasoning_tokens", 0) or 0,
    }
    if any(type(n) is not int or n < 0 for n in counts.values()):
        return None
    if counts["cached_input_tokens"] > counts["input_tokens"] or counts["reasoning_tokens"] > counts["output_tokens"]:
        return None
    return counts


def load_pricing(path=None):
    return json.loads(
        Path(path or os.environ.get("COTERA_LLM_PRICING_PATH") or PRICING_PATH).read_text(encoding="utf-8")
    )


def rates_for(pricing, model):
    rates = pricing["models"][model]
    if not {"input", "output"} <= rates.keys():
        raise ValueError("Informe os preços de entrada e saída.")
    for name in ("input", "output", "cached_input"):
        if name in rates:
            amount = Decimal(rates[name])
            if not amount.is_finite() or amount < 0:
                raise ValueError("Preços precisam ser finitos e não negativos.")
    return rates


def estimated_cost(usage, rates):
    if usage is None or rates is None:
        return None
    cached = usage.get("cached_input_tokens", 0)
    # Sem tarifa de cache publicada na tabela, usa o preço integral de entrada.
    incoming = (usage["input_tokens"] - cached) * Decimal(rates["input"])
    incoming += cached * Decimal(rates.get("cached_input", rates["input"]))
    return (incoming + usage["output_tokens"] * Decimal(rates["output"])) / Decimal(1_000_000)


def reserved_tokens(kwargs):
    """Limite conservador por bytes UTF-8, incluindo schema, instruções e framing."""
    return len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 4096 + kwargs["max_output_tokens"]
