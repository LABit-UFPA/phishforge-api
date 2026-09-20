-- Fundacao do modulo de avaliacao por especialistas (issue #36).
--
-- O corpus gerado pelo PhishForge precisa de uma terceira perspectiva
-- de validacao: especialistas avaliando, as cegas, uma rodada de itens
-- (o ROADMAP_PESQUISA_2027 preve anotacao de pistas por 2 anotadores
-- com concordancia Cohen's kappa). Esta migration cria so a fundacao
-- de dados e acesso -- rodadas, itens da rodada e especialistas. As
-- tabelas `avaliacoes` e `avaliacao_anotacoes` (que dependem de
-- `especialistas` e de `cues`) ficam para a issue #37, para nao
-- acoplar as duas num PR grande demais de revisar.

CREATE TABLE avaliacao_rodadas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome VARCHAR(120) NOT NULL,
    descricao TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'rascunho'
        CHECK (status IN ('rascunho', 'aberta', 'encerrada')),
    -- TCLE versionado como DADO, nao no codigo: o CEP pode exigir
    -- alteracao durante a coleta, e quem consentiu com a versao
    -- anterior precisa reconsentir.
    tcle_versao VARCHAR(32) NOT NULL,
    tcle_texto_md TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE avaliacao_rodadas IS 'Uma rodada de avaliacao por especialistas: conjunto fixo de itens + TCLE versionado (issue #36).';
COMMENT ON COLUMN avaliacao_rodadas.status IS 'rascunho -> aberta -> encerrada. A composicao dos itens congela ao abrir (issue #38).';
COMMENT ON COLUMN avaliacao_rodadas.tcle_versao IS 'Versao vigente do TCLE. Um especialista com consentimento de outra versao precisa reconsentir.';

CREATE TRIGGER set_timestamp_avaliacao_rodadas
BEFORE UPDATE ON avaliacao_rodadas
FOR EACH ROW
EXECUTE PROCEDURE update_updated_at_column();

CREATE TABLE avaliacao_rodada_itens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rodada_id UUID NOT NULL REFERENCES avaliacao_rodadas(id) ON DELETE CASCADE,
    -- RESTRICT: apagar item ja avaliado destruiria o corpus no meio da coleta.
    email_id UUID NOT NULL REFERENCES phishing_emails(id) ON DELETE RESTRICT,
    ordem_canonica INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_rodada_item UNIQUE (rodada_id, email_id),
    CONSTRAINT uq_rodada_ordem UNIQUE (rodada_id, ordem_canonica)
);

COMMENT ON COLUMN avaliacao_rodada_itens.email_id IS 'ON DELETE RESTRICT: apagar um item que ja esta numa rodada destruiria o corpus no meio da coleta.';
COMMENT ON COLUMN avaliacao_rodada_itens.ordem_canonica IS 'Ordem fixa do item na rodada. Cada especialista ve os itens numa ordem propria sorteada (issue #37); esta e so a referencia estavel.';

CREATE INDEX idx_rodada_itens_rodada ON avaliacao_rodada_itens USING btree (rodada_id);
CREATE INDEX idx_rodada_itens_email ON avaliacao_rodada_itens USING btree (email_id);

CREATE TABLE especialistas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome VARCHAR(120) NOT NULL,
    sobrenome VARCHAR(120) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    papel VARCHAR(16) NOT NULL DEFAULT 'especialista'
        CHECK (papel IN ('especialista', 'pesquisador')),
    -- SHA-256 do codigo de acesso. O texto claro aparece UMA vez, na
    -- resposta do POST que criou o especialista, e nunca mais.
    -- SHA-256 (e nao bcrypt) basta: 16 chars de um alfabeto de ~31 =
    -- ~79 bits, gerado por secrets (nao escolhido por humano), nao
    -- reutilizado -- evita introduzir passlib como dependencia nova.
    codigo_hash CHAR(64) NOT NULL UNIQUE,
    codigo_prefixo VARCHAR(8) NOT NULL,
    rodada_id UUID REFERENCES avaliacao_rodadas(id) ON DELETE RESTRICT,
    -- Perfil basico para caracterizar a amostra no artigo:
    -- {anos_experiencia, area_atuacao, formacao}
    perfil_json JSONB,
    perfil_em TIMESTAMPTZ,
    consentimento_versao VARCHAR(32),
    consentimento_em TIMESTAMPTZ,
    -- LGPD: revogar nao apaga linhas (corromperia analises ja rodadas);
    -- marca a data, recusa sessoes e exclui dos exports.
    revogado_em TIMESTAMPTZ,
    ultimo_acesso_em TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE especialistas IS 'Pessoas que avaliam (papel especialista) ou administram (papel pesquisador) uma rodada. Login por codigo de acesso, sem senha (issue #36).';
COMMENT ON COLUMN especialistas.codigo_hash IS 'SHA-256 do codigo de acesso. Nunca exposto por nenhuma resposta da API.';
COMMENT ON COLUMN especialistas.codigo_prefixo IS 'Primeiros 4 caracteres do codigo, so para o pesquisador identificar qual codigo e de quem sem guardar o codigo.';
COMMENT ON COLUMN especialistas.revogado_em IS 'LGPD: preenchido = acesso recusado imediatamente (mesmo com JWT ainda valido) e fora de todos os exports. A linha nao e apagada.';

CREATE INDEX idx_especialistas_rodada ON especialistas USING btree (rodada_id);

CREATE TRIGGER set_timestamp_especialistas
BEFORE UPDATE ON especialistas
FOR EACH ROW
EXECUTE PROCEDURE update_updated_at_column();
