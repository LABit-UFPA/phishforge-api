-- Geracao multicanal (issue #6): website, phone_call e pix_qr.
--
-- Ate aqui a geracao produzia so email: `phishing_emails` tem colunas
-- fixas (receptor, remetente, assunto, conteudo) que nao fazem
-- sentido para os outros 5 canais que o backend Go ja modela em
-- `items.channel` (email | sms | whatsapp | website | phone_call |
-- pix_qr). O golpe mais representativo do cenario brasileiro (Pix,
-- WhatsApp) e justamente o que a geracao nao cobria.
--
-- DUAS decisoes de escopo, deliberadas (ver comentario da issue #6 e
-- da #5, mesmo bloqueio):
--
-- 1. So 3 dos 6 canais entram AGORA: website, phone_call, pix_qr. Os
--    outros dois que faltam (sms, whatsapp) tem shape com valor
--    ANINHADO (`messages: [...]`, `links: [...]`) que o backend Go
--    ainda nao aceita -- `buildDraftContent` (item_draft_service.go)
--    monta `map[string]string`, que nao comporta array de objetos.
--    Frouxar esse tipo e pre-requisito do lado Go (mesmo bloqueio
--    registrado na #5 para o `links` de email). O CHECK abaixo ja
--    inclui os 6 valores (alinhado com o Go), mas a validacao de
--    ENTRADA na API (`app/domain/models/channel.py`) so aceita os 4
--    ja gerenciaveis -- rejeitar sms/whatsapp explicitamente na borda
--    e melhor que aceitar e falhar de forma obscura depois.
--
-- 2. `email` NAO migra para `content_json` nesta issue. As colunas
--    atuais (receptor/remetente/assunto/conteudo/links) continuam
--    sendo a representacao canonica de email -- cues, phish_scale e o
--    dedup do lote (#5, #9, #11b) dependem de `conteudo` como string
--    solta, e reescrever os tres para operar sobre um JSONB generico
--    e um refactor maior, decidido para ficar fora do escopo desta
--    entrega. `content_json` e usado SOMENTE pelos 3 canais novos.
--
-- O CHECK de conjunto abaixo formaliza a regra: linha de email tem as
-- 4 colunas antigas preenchidas E content_json vazio; linha de
-- qualquer outro canal tem content_json preenchido E as 4 colunas
-- antigas vazias. Nunca os dois, nunca nenhum -- mesma filosofia de
-- "completo ou ausente" das constraints da #5/#9.

ALTER TABLE phishing_emails
    ALTER COLUMN receptor DROP NOT NULL,
    ALTER COLUMN remetente DROP NOT NULL,
    ALTER COLUMN assunto DROP NOT NULL,
    ALTER COLUMN conteudo DROP NOT NULL;

ALTER TABLE phishing_emails
    ADD COLUMN channel VARCHAR(32) NOT NULL DEFAULT 'email'
        CHECK (channel IN ('email', 'sms', 'whatsapp', 'website', 'phone_call', 'pix_qr')),
    ADD COLUMN content_json JSONB;

ALTER TABLE phishing_emails
    ADD CONSTRAINT ck_conteudo_por_canal CHECK (
        (channel = 'email'
            AND receptor IS NOT NULL AND remetente IS NOT NULL
            AND assunto IS NOT NULL AND conteudo IS NOT NULL
            AND content_json IS NULL)
        OR
        (channel != 'email'
            AND content_json IS NOT NULL
            AND receptor IS NULL AND remetente IS NULL
            AND assunto IS NULL AND conteudo IS NULL)
    );

COMMENT ON COLUMN phishing_emails.channel IS 'Canal do item: email (colunas antigas) ou website|phone_call|pix_qr (content_json). sms|whatsapp aceitos no CHECK para alinhar com o backend Go, mas rejeitados na validacao de entrada da API ate o bloqueio do lado Go ser resolvido (issue #6, mesma causa da #5).';
COMMENT ON COLUMN phishing_emails.content_json IS 'Conteudo dos canais NAO-email, shape variavel por canal (ver app/domain/models/channel_content.py). NULL para email -- as colunas antigas continuam sendo a representacao canonica desse canal.';

CREATE INDEX idx_phishing_emails_channel ON phishing_emails USING btree (channel);

-- generation_jobs (issue #11b) tambem precisa saber o canal do lote,
-- para o polling (GET /generate/batch/{job_id}) mostrar o que foi de
-- fato pedido -- mesma logica de auditabilidade que ja vale para
-- `total`/`malicious_ratio` na mesma tabela.
ALTER TABLE generation_jobs
    ADD COLUMN channel VARCHAR(32) NOT NULL DEFAULT 'email'
        CHECK (channel IN ('email', 'sms', 'whatsapp', 'website', 'phone_call', 'pix_qr'));

COMMENT ON COLUMN generation_jobs.channel IS 'Canal solicitado para o lote inteiro (issue #6) -- um lote e sempre de um unico canal, nao misto.';
