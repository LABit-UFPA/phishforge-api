-- Job de geracao em lote assincrono (issue #11b).
--
-- Antes desta migration, POST /generate/batch era sequencial dentro
-- da propria request HTTP: um lote de total=100 levava minutos numa
-- unica conexao, e qualquer ingress/proxy encerrava antes do fim --
-- o cliente ficava sem resposta mesmo com os itens ja gravados no
-- banco. Esta tabela guarda o ESTADO do job, para o endpoint aceitar
-- a requisicao com 202 e devolver o resultado por polling em
-- GET /api/v1/generate/batch/{job_id}, sobrevivendo a restart do
-- processo (o job em si roda em background dentro do mesmo processo
-- que o aceitou -- nao ha fila distribuida; um restart NO MEIO do
-- processamento deixa o job preso em "em_progresso", limitacao
-- registrada e aceita para o escopo desta issue).

CREATE TABLE generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(32) NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'em_progresso', 'concluido', 'concluido_com_falhas', 'falhou')),

    -- Parametros da requisicao original, para o worker em background
    -- ter tudo que precisa sem depender de estado em memoria.
    context TEXT NOT NULL,
    difficulties JSONB NOT NULL,
    total INT NOT NULL,
    malicious_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,

    -- Preenchidos durante o processamento.
    distribution JSONB,
    total_generated INT NOT NULL DEFAULT 0,
    total_failed INT NOT NULL DEFAULT 0,
    total_discarded INT NOT NULL DEFAULT 0,
    item_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    failures JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

COMMENT ON TABLE generation_jobs IS 'Estado de um job de geracao em lote assincrono. Sobrevive a restart do processo (o estado e lido do banco, nao de memoria) -- nao sobrevive a interrupcao NO MEIO do processamento (nao ha retomada automatica, ver issue #11b).';
COMMENT ON COLUMN generation_jobs.status IS 'pendente: aceito, ainda nao comecou. em_progresso: gerando. concluido: todos os itens pedidos foram gerados. concluido_com_falhas: gerou pelo menos 1, mas nem todos. falhou: nenhum item foi gerado (falha no pipeline ou todos os itens falharam).';
COMMENT ON COLUMN generation_jobs.item_ids IS 'IDs (phishing_emails.id) dos itens gerados com sucesso neste job, na ordem de geracao.';
COMMENT ON COLUMN generation_jobs.failures IS 'Lista de {difficulty, is_malicious, error} para cada tentativa que falhou (nao inclui itens descartados por duplicidade -- ver total_discarded).';
COMMENT ON COLUMN generation_jobs.total_discarded IS 'Itens gerados mas descartados por serem quase-duplicados de outro item do mesmo lote (deduplicacao por similaridade de embedding, ver issue #11b) -- nao conta como falha nem como sucesso.';

CREATE INDEX idx_generation_jobs_status ON generation_jobs USING btree (status);
CREATE INDEX idx_generation_jobs_created_at ON generation_jobs USING btree (created_at);

CREATE TRIGGER set_timestamp_generation_jobs
BEFORE UPDATE ON generation_jobs
FOR EACH ROW
EXECUTE PROCEDURE update_updated_at_column();
