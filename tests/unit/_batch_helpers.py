"""Helper compartilhado pelos testes do lote assincrono (issue #11b).

Nao e um arquivo de fixtures (por isso nao se chama conftest.py) --
so uma funcao reaproveitada por varios arquivos de teste.
"""


async def post_batch_and_get_job(client, payload: dict) -> dict:
    """POST /generate/batch seguido do GET do job resultante.

    Com httpx.ASGITransport, BackgroundTasks roda de forma SINCRONA
    dentro do proprio `client.post()` (confirmado experimentalmente
    antes de escrever os testes desta issue) -- entao, com os fakes
    (que nao tem latencia real), o job ja esta no estado final quando
    o POST retorna. Isso NAO reflete o comportamento contra um servidor
    real (la o cliente recebe o 202 antes do processamento terminar de
    verdade) -- e so uma particularidade do transporte de teste.
    """
    post_response = await client.post("/api/v1/generate/batch", json=payload)
    assert post_response.status_code == 202, post_response.text
    job_id = post_response.json()["job_id"]

    get_response = await client.get(f"/api/v1/generate/batch/{job_id}")
    assert get_response.status_code == 200, get_response.text
    return get_response.json()
