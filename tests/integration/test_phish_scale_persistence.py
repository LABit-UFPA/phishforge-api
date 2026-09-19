"""Persistencia do Phish Scale (issue #9) contra Postgres de verdade:
`phish_scale_cue_count`, `phish_scale_premise_alignment` e
`difficulty_estimated`, adicionados por V20260919110000, com o CHECK
de conjunto (os tres juntos ou nenhum) e round-trip via
PhishingEmailRepository.
"""

import asyncpg
import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.difficulty import Difficulty
from app.domain.models.phish_scale import PhishScale, PremiseAlignment
from app.domain.models.phishing_email import PhishingEmail


def _email_de_teste(**overrides) -> PhishingEmail:
    base = dict(
        receptor="alvo@example.com",
        remetente="remetente@example.com",
        assunto="Assunto de teste de integracao",
        conteudo="Conteudo de teste de integracao.",
        explicacao="Explicacao de teste.",
        nivel="dificil",
        categoria="teste_integracao",
        links=[],
        is_malicious=True,
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_create_persiste_e_get_by_id_recupera_o_phish_scale(phishing_repository):
    email = _email_de_teste(
        cues=[Cue(code=CueCode.URGENCY, evidencia="algo")],
        phish_scale=PhishScale(
            cue_count=1,
            premise_alignment=PremiseAlignment.ALTO,
            difficulty_estimated=Difficulty.DIFICIL,
        ),
    )

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido is not None
    assert lido.phish_scale is not None
    assert lido.phish_scale.cue_count == 1
    assert lido.phish_scale.premise_alignment == PremiseAlignment.ALTO
    assert lido.phish_scale.difficulty_estimated == Difficulty.DIFICIL


async def test_email_sem_phish_scale_persiste_none(phishing_repository):
    email = _email_de_teste(is_malicious=False, cues=[], phish_scale=None, nivel="facil")

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido.phish_scale is None


async def test_check_de_conjunto_rejeita_phish_scale_parcial(db_connection):
    """ck_phish_scale_completo_ou_ausente: nao pode existir linha com
    so PARTE dos tres campos preenchida -- dado incompleto pareceria
    "zero" numa agregacao, em vez de "nao se aplica".
    """
    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO phishing_emails
                (receptor, remetente, assunto, conteudo, explicacao, nivel, categoria, links,
                 is_malicious, phish_scale_cue_count)
                VALUES ('a@b.com', 'c@d.com', 'assunto', 'conteudo', 'explicacao', 'facil',
                        'teste', '[]'::jsonb, true, 3)
                """
            )
