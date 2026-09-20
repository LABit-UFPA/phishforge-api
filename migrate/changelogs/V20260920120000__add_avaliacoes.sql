-- Avaliacoes e anotacoes dos especialistas (issue #37).
--
-- `avaliacoes` guarda, por especialista e por item da rodada, o
-- julgamento humano (dificuldade percebida, adequacao, qualidade,
-- justificativa). `avaliacao_anotacoes` guarda os trechos que o
-- especialista marcou como pista, com a pista da taxonomia (`cues`).
--
-- `avaliacoes` NAO guarda copia de `nivel`: a verdade fica em
-- phishing_emails.nivel e o cruzamento acontece so no export (#38).
-- Nada no caminho do especialista precisa ler aquele campo, o que
-- reforca o cegamento por estrutura em vez de por disciplina de codigo.

CREATE TABLE avaliacoes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    especialista_id UUID NOT NULL REFERENCES especialistas(id) ON DELETE CASCADE,
    rodada_item_id UUID NOT NULL REFERENCES avaliacao_rodada_itens(id) ON DELETE CASCADE,
    -- Posicao em que ESTE especialista viu ESTE item. Sorteada por
    -- especialista: se todos veem o item 30 por ultimo, "item 30 teve
    -- avaliacao pior" e inseparavel de "todo mundo estava cansado".
    ordem_apresentacao INT NOT NULL CHECK (ordem_apresentacao >= 1),
    status VARCHAR(16) NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'concluida')),
    dificuldade_percebida VARCHAR(16)
        CHECK (dificuldade_percebida IN ('facil', 'medio', 'dificil')),
    adequado_uso_educacional BOOLEAN,
    qualidade_geral SMALLINT CHECK (qualidade_geral BETWEEN 1 AND 5),
    justificativa TEXT,
    comentario TEXT,
    tempo_ms INT CHECK (tempo_ms >= 0),
    concluida_em TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_avaliacao_especialista_item UNIQUE (especialista_id, rodada_item_id),
    CONSTRAINT uq_avaliacao_ordem UNIQUE (especialista_id, ordem_apresentacao),
    -- Integridade no banco, nao so no Pydantic: avaliacao "concluida"
    -- sem campo obrigatorio vira NaN no export, descoberto meses depois.
    CONSTRAINT ck_avaliacao_concluida CHECK (
        status = 'pendente' OR (
            dificuldade_percebida IS NOT NULL
            AND adequado_uso_educacional IS NOT NULL
            AND qualidade_geral IS NOT NULL
            AND justificativa IS NOT NULL
            AND concluida_em IS NOT NULL
        )
    )
);

COMMENT ON TABLE avaliacoes IS 'Julgamento de um especialista sobre um item de uma rodada (issue #37). Criadas todas de uma vez, como pendentes, no primeiro acesso do especialista.';
COMMENT ON COLUMN avaliacoes.ordem_apresentacao IS 'Posicao em que ESTE especialista ve ESTE item, sorteada por especialista para a ordem nao se confundir com o efeito do item.';
COMMENT ON COLUMN avaliacoes.tempo_ms IS 'Tempo que o especialista levou no item, informado pelo cliente (nao verificado).';

CREATE INDEX idx_avaliacoes_especialista ON avaliacoes USING btree (especialista_id);
CREATE INDEX idx_avaliacoes_rodada_item ON avaliacoes USING btree (rodada_item_id);

CREATE TRIGGER set_timestamp_avaliacoes
BEFORE UPDATE ON avaliacoes
FOR EACH ROW
EXECUTE PROCEDURE update_updated_at_column();

CREATE TABLE avaliacao_anotacoes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    avaliacao_id UUID NOT NULL REFERENCES avaliacoes(id) ON DELETE CASCADE,
    cue_id UUID NOT NULL REFERENCES cues(id) ON DELETE RESTRICT,
    -- Nem toda pista vive no corpo: sender_domain_mismatch e typosquat
    -- aparecem no REMETENTE. Sem o campo, os offsets sao ambiguos.
    campo VARCHAR(16) NOT NULL DEFAULT 'conteudo'
        CHECK (campo IN ('conteudo', 'assunto', 'remetente')),
    span_start INT NOT NULL CHECK (span_start >= 0),
    span_end INT NOT NULL CHECK (span_end > span_start),
    -- Redundante com os offsets DE PROPOSITO: permite detectar na
    -- analise uma anotacao cujos offsets nao batem mais com o texto,
    -- em vez de descobrir isso como ruido inexplicavel.
    trecho TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Sem UNIQUE (avaliacao_id, cue_id) de proposito: o especialista PODE
-- marcar a mesma pista em varios trechos (tres apelos de urgencia sao
-- tres evidencias, nao uma).

COMMENT ON TABLE avaliacao_anotacoes IS 'Trechos que o especialista marcou como pista (issue #37). Substituidos por inteiro a cada PUT da avaliacao.';
COMMENT ON COLUMN avaliacao_anotacoes.span_start IS 'Offset inicial em CODE POINTS (len() do Python), nao unidades UTF-16 do JavaScript.';
COMMENT ON COLUMN avaliacao_anotacoes.trecho IS 'Texto marcado, redundante com os offsets de proposito: o backend recusa (422) quando campo[span_start:span_end] != trecho.';

CREATE INDEX idx_avaliacao_anotacoes_avaliacao ON avaliacao_anotacoes USING btree (avaliacao_id);
CREATE INDEX idx_avaliacao_anotacoes_cue ON avaliacao_anotacoes USING btree (cue_id);
