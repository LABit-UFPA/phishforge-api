"""Persistencia do job de lote assincrono (issue #11b) contra Postgres
de verdade: schema aplicado pela migration V20260918200000, tipos
JSONB lidos/escritos via json.dumps/loads (sem codec asyncpg
customizado -- mesmo padrao de phishing_repository.py), e sobrevivencia
a "restart do processo" (o requisito central da issue: o estado vive
no banco, nao em memoria do worker).
"""

from uuid import uuid4

from app.domain.models.generation_job import GenerationFailure, JobStatus
from tests.integration.conftest import nova_conexao_real
from app.infra.database.repositories.generation_job_repository import GenerationJobRepository


async def test_get_by_id_de_job_inexistente_retorna_none(generation_job_repository):
    assert await generation_job_repository.get_by_id(uuid4()) is None


async def test_ciclo_de_vida_completo_do_job(generation_job_repository):
    job_id = await generation_job_repository.create(
        context="cobranca de fatura",
        difficulties=["facil", "medio"],
        total=5,
        malicious_ratio=0.6,
    )

    job = await generation_job_repository.get_by_id(job_id)
    assert job.status == JobStatus.PENDENTE
    assert job.context == "cobranca de fatura"
    assert job.difficulties == ["facil", "medio"]
    assert job.total == 5
    assert job.malicious_ratio == 0.6
    assert job.distribution is None
    assert job.item_ids == []
    assert job.failures == []
    assert job.created_at is not None

    await generation_job_repository.mark_em_progresso(job_id, {"facil": 3, "medio": 2})
    job = await generation_job_repository.get_by_id(job_id)
    assert job.status == JobStatus.EM_PROGRESSO
    assert job.distribution == {"facil": 3, "medio": 2}

    item_ids = [uuid4(), uuid4()]
    failures = [{"difficulty": "medio", "is_malicious": True, "error": "falha simulada"}]
    await generation_job_repository.update_progress(
        job_id,
        total_generated=2,
        total_failed=1,
        total_discarded=1,
        item_ids=item_ids,
        failures=failures,
    )
    job = await generation_job_repository.get_by_id(job_id)
    assert job.total_generated == 2
    assert job.total_failed == 1
    assert job.total_discarded == 1
    assert job.item_ids == item_ids
    assert job.failures == [GenerationFailure(**failures[0])]
    # Ainda em progresso -- update_progress nao decide o status final,
    # so mark_finished decide (issue #11b: chamado a cada item, para o
    # polling refletir progresso parcial de um lote ainda rodando).
    assert job.status == JobStatus.EM_PROGRESSO
    assert job.completed_at is None

    await generation_job_repository.mark_finished(job_id, JobStatus.CONCLUIDO_COM_FALHAS)
    job = await generation_job_repository.get_by_id(job_id)
    assert job.status == JobStatus.CONCLUIDO_COM_FALHAS
    assert job.error_message is None
    assert job.completed_at is not None


async def test_job_falhou_guarda_mensagem_de_erro(generation_job_repository):
    job_id = await generation_job_repository.create(
        context="cobranca de fatura", difficulties=["facil"], total=1, malicious_ratio=1.0
    )

    await generation_job_repository.mark_finished(
        job_id, JobStatus.FALHOU, error_message="Erro ao montar contexto: falha simulada"
    )

    job = await generation_job_repository.get_by_id(job_id)
    assert job.status == JobStatus.FALHOU
    assert job.error_message == "Erro ao montar contexto: falha simulada"


async def test_estado_sobrevive_a_restart_do_processo(generation_job_repository):
    """O requisito central da #11b: o worker e o endpoint de polling
    nunca compartilham estado em memoria -- so o banco. Aqui,
    `generation_job_repository` (a "instancia antiga") escreve, e uma
    SEGUNDA instancia, com sua PROPRIA DatabaseConnection/pool (a
    "instancia nova, pos-restart"), le -- provando que nada depende de
    estado do processo que criou o job.
    """
    job_id = await generation_job_repository.create(
        context="aviso de manutencao", difficulties=["dificil"], total=1, malicious_ratio=0.0
    )
    await generation_job_repository.mark_em_progresso(job_id, {"dificil": 1})

    conexao_pos_restart = nova_conexao_real()
    await conexao_pos_restart.create_pool()
    try:
        repositorio_pos_restart = GenerationJobRepository(db=conexao_pos_restart)
        job = await repositorio_pos_restart.get_by_id(job_id)

        assert job is not None
        assert job.status == JobStatus.EM_PROGRESSO
        assert job.distribution == {"dificil": 1}
        assert job.malicious_ratio == 0.0
    finally:
        await conexao_pos_restart.close_pool()
