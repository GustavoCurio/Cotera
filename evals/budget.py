"""Limite conservador de US$ 3, compartilhado entre modelos; sem retries."""
import json
from decimal import Decimal

MILLION = Decimal(1_000_000)
MAX_BUDGET_USD = Decimal('3')


class BudgetExceeded(RuntimeError):
    """Chamada não iniciada porque a reserva excederia o orçamento."""


def rates_for(pricing, model):
    rates = pricing['models'][model]
    for name in ('input', 'output'):
        if not Decimal(rates[name]).is_finite() or Decimal(rates[name]) <= 0:
            raise ValueError('Precos de entrada e saida devem ser positivos e finitos.')
    return rates


def usage_from(response):
    usage = getattr(response, 'usage', None)
    if usage is None:
        return None
    incoming, outgoing = getattr(usage, 'input_tokens', None), getattr(usage, 'output_tokens', None)
    details = getattr(usage, 'input_tokens_details', None)
    cached = getattr(details, 'cached_tokens', 0) or 0
    if not isinstance(incoming, int) or not isinstance(outgoing, int) or min(incoming, outgoing, cached) < 0 or cached > incoming:
        return None
    return {'input_tokens': incoming, 'output_tokens': outgoing, 'cached_input_tokens': cached}


def estimated_cost(usage, rates):
    if usage is None:
        return None
    # Usa preço integral de entrada, inclusive cache: estimativa conservadora e reproduzível.
    return (usage['input_tokens'] * Decimal(rates['input']) + usage['output_tokens'] * Decimal(rates['output'])) / MILLION


class Budget:
    def __init__(self, limit=MAX_BUDGET_USD):
        self.limit = Decimal(limit)
        if not self.limit.is_finite() or not 0 < self.limit <= MAX_BUDGET_USD:
            raise ValueError('Orcamento deve estar entre zero (exclusivo) e US$ 3.')
        self.accounted = Decimal(0)
        self.stopped = False

    def reserve(self, kwargs, rates):
        # Um token de texto tem ao menos um byte. Inclui schema/instruções/catálogo e
        # margem adicional de 4096 tokens para framing. Não usa aproximação chars/4.
        incoming = len(json.dumps(kwargs, ensure_ascii=False).encode('utf-8')) + 4096
        outgoing = kwargs['max_output_tokens']
        amount = (incoming * Decimal(rates['input']) + outgoing * Decimal(rates['output'])) / MILLION
        if self.stopped or self.accounted + amount > self.limit:
            raise BudgetExceeded('Orcamento insuficiente para reservar a proxima chamada.')
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
        self.usage = None
        self.cost = None
        self.started = False

    def create(self, **kwargs):
        reserved = self.budget.reserve(kwargs, self.rates)
        self.started = True
        try:
            self.response = self.client.responses.create(**kwargs)
            self.usage = usage_from(self.response)
            self.cost = estimated_cost(self.usage, self.rates)
            return self.response
        finally:
            self.budget.settle(reserved, self.usage, self.rates)
