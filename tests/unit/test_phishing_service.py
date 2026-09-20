"""Teste direto de PhishingEmailService (a classe real, não
tests/fakes.py::FakePhishingService) para a validação estrita de
`nivel` introduzida na issue #2.

Usa um repositório fake mínimo em vez de Postgres real -- o que este
teste audita é a lógica de validação em `create_email`, não a
persistência (essa parte está em
tests/integration/test_difficulty_persistence.py).
"""

import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.phishing_service import PhishingEmailService


class _RepoQueNuncaDeveriaSerChamado:
    async def create(self, email):
        raise AssertionError(
            "repository.create() foi chamado com nivel invalido -- "
            "a validacao deveria ter barrado antes disso"
        )


def _email_de_teste(nivel: str, **overrides) -> PhishingEmail:
    base = dict(
        receptor="alvo@example.com",
        remetente="remetente@example.com",
        assunto="Assunto de teste",
        conteudo="Conteudo de teste",
        explicacao="Explicacao de teste",
        nivel=nivel,
        categoria="teste",
        links=[],
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_create_email_rejeita_nivel_fora_do_vocabulario():
    service = PhishingEmailService(
        repository=_RepoQueNuncaDeveriaSerChamado(), analytics_repository=None
    )
    email = _email_de_teste(nivel="nivel_que_nao_existe")

    with pytest.raises(ValueError, match="nivel invalido"):
        await service.create_email(email)


async def test_create_email_rejeita_item_legitimo_com_pistas(monkeypatch):
    """Issue #5, passo 9: ResponseGenerator._validar_cues ja esvazia
    `cues` para item legitimo antes disso -- este e o segundo cinto de
    seguranca, para qualquer chamador que monte um PhishingEmail sem
    passar pelo gerador.
    """
    service = PhishingEmailService(
        repository=_RepoQueNuncaDeveriaSerChamado(), analytics_repository=None
    )
    email = _email_de_teste(
        nivel="facil",
        is_malicious=False,
        cues=[Cue(code=CueCode.URGENCY, evidencia="algo")],
    )

    with pytest.raises(ValueError, match="pista"):
        await service.create_email(email)


@pytest.mark.parametrize("nivel_valido", ["facil", "medio", "dificil"])
async def test_list_emails_aceita_sinonimo_de_nivel_como_filtro(nivel_valido, monkeypatch):
    """Diferente de create_email: aqui um sinonimo e conveniencia de
    busca, nao dado a persistir -- comportamento preservado (nao e o
    escopo de validacao estrita da #2).
    """

    chamadas = []

    class _RepoDeBusca:
        async def list_emails(self, categoria, nivel, search, limit, offset):
            chamadas.append(nivel)
            return []

    service = PhishingEmailService(repository=_RepoDeBusca(), analytics_repository=None)

    sinonimo_em_ingles = {"facil": "easy", "medio": "medium", "dificil": "hard"}[nivel_valido]
    await service.list_emails(nivel=sinonimo_em_ingles)

    assert chamadas == [nivel_valido]


async def test_list_emails_repassa_todos_os_filtros_juntos_com_sinonimo_normalizado():
    """Issue #39: o servico nao escolhe um filtro; entrega todos de uma vez
    ao repositorio (e normaliza so o sinonimo de `nivel`).
    """
    recebido = {}

    class _Repo:
        async def list_emails(self, categoria, nivel, search, limit, offset):
            recebido.update(categoria=categoria, nivel=nivel, search=search, limit=limit, offset=offset)
            return []

    service = PhishingEmailService(repository=_Repo(), analytics_repository=None)

    await service.list_emails(categoria="rh", nivel="HARD", search="banco", limit=10, offset=20)

    assert recebido == {"categoria": "rh", "nivel": "dificil", "search": "banco", "limit": 10, "offset": 20}
