-- Adiciona o rotulo malicioso/legitimo aos itens (issue #3).
--
-- Ate aqui, a API gerava exclusivamente phishing -- todo registro em
-- phishing_emails era malicioso por construcao. Sem item legitimo no
-- corpus nao existe taxa de falso alarme nem d' (deteccao de sinal),
-- que e a metrica central do estudo (ver phishing-quest-api #23).
--
-- Default TRUE faz o backfill do que ja existe sem precisar de UPDATE
-- explicito: todo registro atual E phishing por construcao. O default
-- fica registrado aqui de proposito, mas cada INSERT novo (a partir da
-- aplicacao) passa a informar o valor explicitamente -- ver
-- PhishingEmailRepository.create.

ALTER TABLE phishing_emails
    ADD COLUMN is_malicious BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN phishing_emails.is_malicious IS 'true = item e uma tentativa de phishing; false = item legitimo (necessario para medir taxa de falso alarme e d-prime).';

CREATE INDEX idx_phishing_emails_is_malicious ON phishing_emails USING btree (is_malicious);
