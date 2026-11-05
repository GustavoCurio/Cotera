"""Limite conservador de US$ 3, compartilhado por todos os envios e modelos."""

import json
from decimal import Decimal

from cotera.errors import BudgetError
from cotera.usage import estimated_cost, usage_from
from cotera.usage import rates_for as rates_for

MILLION = Decimal(1_000_000)
MAX_BUDGET_USD = Decimal("3")


class BudgetExceeded(BudgetError):
    """Chamada não iniciada porque a reserva excederia o orçamento."""


class Budget:
    def __init__(self, limit=MAX_BUDGET_USD):
        self.limit = Decimal(limit)
        if not self.limit.is_finite() or not 0 < self.limit <= MAX_BUDGET_USD:
            raise ValueError("Orcamento deve estar entre zero (exclusivo) e US$ 3.")
        self.accounted = Decimal(0)
        self.stopped = False

    def reserve(self, kwargs, rates):
        # Um token de texto tem ao menos um byte. Inclui schema/instruções/catálogo e
        # margem adicional de 4096 tokens para framing. Não usa aproximação chars/4.
        incoming = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 4096
        outgoing = kwargs["max_output_tokens"]
        amount = (incoming * Decimal(rates["input"]) + outgoing * Decimal(rates["output"])) / MILLION
        if self.stopped or self.accounted + amount > self.limit:
            raise BudgetExceeded()
        self.accounted += amount
        return amount

    def settle(self, reserved, usage, rates):
        cost = estimated_cost(usage, rates)
        if cost is not None:
            self.accounted += cost - reserved
            if cost > reserved:
                self.stopped = True
        else:
            # Sem usage não se sabe a cobrança: mantém a reserva e interrompe envios.
            self.stopped = True


class ObservedClient:
    """Proxy injetável: observa o caminho real extract(mode='ai') sem substituí-lo."""

    def __init__(self, client, budget, rates):
        self.client, self.budget, self.rates = client, budget, rates
        self.responses = self
        self.response = None
        self.started = False

    def create(self, **kwargs):
        reserved = self.budget.reserve(kwargs, self.rates)
        self.started = True
        usage = None
        try:
            self.response = self.client.responses.create(**kwargs)
            usage = usage_from(self.response)
            return self.response
        finally:
            # Nunca reutiliza usage da chamada anterior se o próximo envio falhar.
            self.budget.settle(reserved, usage, self.rates)
