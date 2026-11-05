"""Falhas de extração com códigos estáveis e mensagens públicas sem dados do provedor."""


class ProviderError(RuntimeError):
    """Base compatível para falhas esperadas da extração externa."""

    code = "provider_error"
    message = "Não foi possível extrair com IA. Tente novamente ou use o modelo local."

    def __init__(self):
        super().__init__(self.message)
        self.metadata = {}


class TransientProviderError(ProviderError):
    code = "provider_transient"
    message = "O serviço de IA está temporariamente indisponível. Tente mais tarde ou use o modelo local."


class AuthenticationProviderError(ProviderError):
    code = "provider_auth"
    message = "O serviço de IA não autorizou o acesso. Confira as credenciais e permissões no servidor."


class ExtractionValidationError(ProviderError):
    code = "extraction_validation"
    message = (
        "A IA retornou dados inválidos mesmo após uma tentativa de correção. Confira o documento ou use o modelo local."
    )


class EvidenceError(ExtractionValidationError):
    code = "extraction_evidence"
    message = (
        "A IA retornou valores sem evidência válida mesmo após uma tentativa de correção. Revise o documento original."
    )


class RefusalError(ProviderError):
    code = "provider_refusal"
    message = "O serviço de IA recusou a extração deste documento. Use o modelo local ou revise o arquivo."


class IncompleteResponseError(ProviderError):
    code = "provider_incomplete"
    message = "A resposta da IA ficou incompleta. Revise o documento ou use o modelo local."


class BudgetError(ProviderError):
    code = "extraction_budget"
    message = "A extração foi interrompida para respeitar o limite de tokens ou custo. Revise o orçamento configurado."
