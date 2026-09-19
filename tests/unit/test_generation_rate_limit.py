"""Rate limit por IP nos endpoints de geracao (issue #7): protege
contra abuso da chave da OpenAI e contra loop acidental de um
frontend disparando geracoes em sequencia.

`GENERATION_RATE_LIMIT` (default "20/minute") e lido por
`app/core/security.py::limiter` no momento em que
`app/api/v1/endpoints/generator.py` e importado -- uma unica vez por
processo, nao por teste -- entao o teste exercita o valor default de
verdade, nao um valor injetado. `main.create_app()` chama
`limiter.reset()` a cada app nova (ver comentario la), o que e o que
garante que este teste nao seja afetado por nenhum outro teste que
tambem chamou /generate antes, e vice-versa.
"""

from app.core.config import settings


async def test_estourar_o_limite_devolve_429(client):
    limite, _unidade = settings.GENERATION_RATE_LIMIT.split("/")
    n = int(limite)

    respostas = [
        await client.post(
            "/api/v1/generate", json={"context": "ctx", "difficulty": "facil"}
        )
        for _ in range(n)
    ]
    assert all(r.status_code == 200 for r in respostas)

    resposta_excedente = await client.post(
        "/api/v1/generate", json={"context": "ctx", "difficulty": "facil"}
    )
    assert resposta_excedente.status_code == 429
