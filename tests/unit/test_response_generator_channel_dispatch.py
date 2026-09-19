"""ResponseGenerator wiring dos canais (issue #6, sms/whatsapp
desbloqueados pela phishing-quest-api #68): a construcao real (sem
chamada de rede -- so monta objetos LangChain) precisa expor uma chain
para cada combinacao (canal, is_malicious) que `generate_channel_item`
despacha via `_chains_por_canal`.

Os testes HTTP de test_channel_generation.py usam FakeResponseGenerator,
que nunca executa o `__init__` real -- este teste e o unico que
exercita a construcao de verdade e pegaria um erro de wiring (import
errado, variavel nao definida, chave faltando no dict de dispatch) que
os fakes nao pegam.
"""

from app.domain.services.response_generator import ResponseGenerator

_CANAIS_COM_CONTENT_JSON = ["website", "phone_call", "pix_qr", "sms", "whatsapp"]


def test_todas_as_combinacoes_de_canal_tem_chain_configurada():
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")

    for canal in _CANAIS_COM_CONTENT_JSON:
        for is_malicious in (True, False):
            chave = (canal, is_malicious)
            assert chave in generator._chains_por_canal, f"faltando chain para {chave}"
            assert generator._chains_por_canal[chave] is not None


def test_chain_maliciosa_e_legitima_sao_objetos_diferentes():
    """Mesma garantia de design de #3 aplicada aos canais novos: chain
    maliciosa e legitima do MESMO canal precisam ser objetos distintos
    -- nao a mesma chain reaproveitada com uma flag.
    """
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")

    for canal in _CANAIS_COM_CONTENT_JSON:
        maliciosa = generator._chains_por_canal[(canal, True)]
        legitima = generator._chains_por_canal[(canal, False)]
        assert maliciosa is not legitima
