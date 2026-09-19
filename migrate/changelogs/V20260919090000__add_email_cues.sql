-- Anotacao estruturada de pistas de phishing na geracao (issue #5).
--
-- Ate aqui, `explicacao` era o UNICO registro de quais tecnicas de
-- phishing um item usa, e era texto livre. O backend Go tem uma
-- taxonomia de 10 pistas com codigos estaveis e UUIDs FIXOS
-- (phishing-quest-api, migration V20260917110000__add_cues_tables.sql)
-- da qual tres mecanicas inteiras dependem (byCue em /me/stats,
-- selecao adaptativa, fila Leitner) e nenhuma delas tem alimentacao
-- automatica hoje: sem pista anotada, o Leitner (que itera sobre
-- item_cues) nao cria agendamento nenhum.
--
-- `cues` replica a taxonomia aqui com os MESMOS 10 UUIDs LITERAIS (nao
-- gen_random_uuid()) e os MESMOS codigos -- e o que permite ao Go
-- popular sua propria item_cues a partir da resposta desta API sem
-- lookup por texto nem tabela de-para, exatamente o que a issue pede
-- ("Compartilhar a taxonomia de pistas entre os projetos").
--
-- `email_cues` e o equivalente local de item_cues: liga um
-- phishing_email as pistas que o LLM anotou nele, com o span (posicao
-- no `conteudo`) quando localizavel -- ResponseGenerator._validar_cues
-- ja garante que um span presente bate com a evidencia declarada
-- antes de chegar aqui.

CREATE TABLE cues (
    id UUID PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    label_pt VARCHAR(255) NOT NULL,
    category VARCHAR(32) NOT NULL
        CHECK (category IN ('technical', 'psychological')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE cues IS 'Taxonomia canonica de pistas de phishing, espelhada do phishing-quest-api (migration V20260917110000) com os MESMOS UUIDs -- fonte unica de vocabulario entre os dois backends.';
COMMENT ON COLUMN cues.id IS 'UUID FIXO, identico ao do backend Go. Nunca gerar por gen_random_uuid(): a igualdade dos ids entre os dois bancos e o que permite ao Go popular item_cues sem lookup por texto.';
COMMENT ON COLUMN cues.code IS 'Identificador estavel usado no structured output do LLM (app.domain.models.cue.CueCode) e nos payloads da API (ex.: typosquat, urgency).';
COMMENT ON COLUMN cues.category IS 'Agrupamento amplo: technical (dominio, link, anexo) ou psychological (urgencia, autoridade, escassez).';

INSERT INTO cues (id, code, label_pt, category) VALUES
    ('00000000-0000-0000-0000-000000000001', 'sender_domain_mismatch', 'Domínio do remetente não corresponde à organização', 'technical'),
    ('00000000-0000-0000-0000-000000000002', 'typosquat', 'Domínio com erro de digitação proposital (typosquatting)', 'technical'),
    ('00000000-0000-0000-0000-000000000003', 'homoglyph', 'Caractere visualmente semelhante usado para enganar (homóglifo)', 'technical'),
    ('00000000-0000-0000-0000-000000000004', 'urgency', 'Apelo à urgência ou prazo curto', 'psychological'),
    ('00000000-0000-0000-0000-000000000005', 'authority', 'Apelo à autoridade (banco, governo, chefia)', 'psychological'),
    ('00000000-0000-0000-0000-000000000006', 'generic_greeting', 'Saudação genérica, sem personalização', 'psychological'),
    ('00000000-0000-0000-0000-000000000007', 'credential_request', 'Solicitação direta de senha ou dado sensível', 'technical'),
    ('00000000-0000-0000-0000-000000000008', 'link_text_mismatch', 'Texto do link não corresponde ao destino real', 'technical'),
    ('00000000-0000-0000-0000-000000000009', 'unexpected_attachment', 'Anexo inesperado ou fora do contexto', 'technical'),
    ('00000000-0000-0000-0000-000000000010', 'scarcity', 'Apelo à escassez ou oferta por tempo limitado', 'psychological')
ON CONFLICT (id) DO NOTHING;

CREATE INDEX idx_cues_code ON cues USING btree (code);

CREATE TABLE email_cues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id UUID NOT NULL REFERENCES phishing_emails(id) ON DELETE CASCADE,
    cue_id UUID NOT NULL REFERENCES cues(id) ON DELETE RESTRICT,
    span_start INT CHECK (span_start >= 0),
    span_end INT CHECK (span_end > span_start),
    evidencia TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Os dois sao NULL juntos (span nao localizado) ou preenchidos
    -- juntos -- nunca um so. ResponseGenerator._validar_cues so emite
    -- essas duas combinacoes.
    CONSTRAINT ck_email_cues_span_par CHECK (
        (span_start IS NULL) = (span_end IS NULL)
    )
);

COMMENT ON TABLE email_cues IS 'Pistas que o LLM anotou como presentes em cada email (issue #5) -- equivalente local do item_cues do backend Go. E o dado que o Go consome para popular sua propria item_cues, sem interpretar texto livre.';
COMMENT ON COLUMN email_cues.span_start IS 'Offset inicial da evidencia no `conteudo` do email, em code points. NULL quando o modelo nao localizou a pista com precisao -- preferimos sem span a um span errado (issue #5, passo 4).';
COMMENT ON COLUMN email_cues.span_end IS 'Offset final (exclusivo) da evidencia. Validado em ResponseGenerator._validar_cues antes da persistencia: conteudo[span_start:span_end] tem que bater com `evidencia`, senao os dois viram NULL (passo 5).';
COMMENT ON COLUMN email_cues.evidencia IS 'Trecho textual que o LLM apontou como evidencia da pista -- pedido no prompt de proposito, para reduzir alucinacao (o modelo precisa citar onde esta).';

CREATE INDEX idx_email_cues_email ON email_cues USING btree (email_id);
CREATE INDEX idx_email_cues_cue ON email_cues USING btree (cue_id);
