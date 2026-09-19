-- Eixos objetivos do NIST Phish Scale (issue #9).
--
-- Ate aqui, o nivel de dificuldade do item era autodeclarado pelo
-- LLM: o prompt descrevia o que caracteriza facil/medio/dificil, o
-- modelo escrevia o email, e o nivel persistido (phishing_emails.nivel)
-- era simplesmente o que foi PEDIDO na request -- nada verificava se o
-- item gerado como dificil de fato ficou mais dificil que um facil.
-- A issue tem evidencia concreta de que o rotulo nao se sustenta:
-- exemplos do app com o MESMO truque de typosquatting rotulados como
-- 'hard' e 'easy'.
--
-- O Phish Scale decompoe "dificil de detectar" em dois eixos
-- auditaveis (ver ResponseGenerator._compute_phish_scale):
--
-- 1. phish_scale_cue_count: quantidade de pistas presentes (issue
--    #5) -- quanto menos pista, mais dificil de perceber.
-- 2. phish_scale_premise_alignment: o quanto o pretexto se encaixa na
--    rotina de quem recebe -- quanto mais alinhado, mais dificil de
--    desconfiar.
--
-- difficulty_estimated e DERIVADO deterministicamente dos dois eixos
-- acima (regra documentada em
-- ResponseGenerator._derivar_dificuldade_estimada) -- nunca um
-- terceiro palpite do modelo, e um campo DIFERENTE de `nivel`
-- (o pedido na request) e de uma futura `difficulty_calibrated`
-- (medida a partir de tentativas reais dos participantes, calculo do
-- backend Go -- ver phishing-quest-api #66). Nomes de coluna
-- alinhados com o que o Go ja tem em `items` para o mapeamento da
-- integracao (phishing-quest-api #62) ser direto.
--
-- Todas nullable: item legitimo (issue #3) nao tem Phish Scale --
-- "dificuldade de detectar phishing" nao se aplica a algo que nao e
-- phishing. O CHECK de conjunto garante que os tres vem juntos ou
-- nenhum vem -- nunca um subconjunto (dado incompleto que pareceria
-- "zero" numa agregacao, em vez de "nao se aplica").

ALTER TABLE phishing_emails
    ADD COLUMN phish_scale_cue_count INT
        CHECK (phish_scale_cue_count >= 0),
    ADD COLUMN phish_scale_premise_alignment VARCHAR(16)
        CHECK (phish_scale_premise_alignment IN ('baixo', 'medio', 'alto')),
    ADD COLUMN difficulty_estimated VARCHAR(16)
        CHECK (difficulty_estimated IN ('facil', 'medio', 'dificil'));

ALTER TABLE phishing_emails
    ADD CONSTRAINT ck_phish_scale_completo_ou_ausente CHECK (
        (phish_scale_cue_count IS NULL AND phish_scale_premise_alignment IS NULL AND difficulty_estimated IS NULL)
        OR
        (phish_scale_cue_count IS NOT NULL AND phish_scale_premise_alignment IS NOT NULL AND difficulty_estimated IS NOT NULL)
    );

COMMENT ON COLUMN phishing_emails.phish_scale_cue_count IS 'Quantidade de pistas anotadas no item (= tamanho de email_cues no momento da geracao). NULL para item legitimo.';
COMMENT ON COLUMN phishing_emails.phish_scale_premise_alignment IS 'baixo|medio|alto -- o quanto o pretexto do item se encaixa na rotina de quem recebe, julgado pelo LLM contra o context da request. NULL para item legitimo.';
COMMENT ON COLUMN phishing_emails.difficulty_estimated IS 'Dificuldade ESTIMADA a priori, derivada deterministicamente de phish_scale_cue_count + phish_scale_premise_alignment (issue #9). Distinto de `nivel` (o pedido na request) e de uma futura difficulty_calibrated (medida a posteriori a partir de tentativas reais -- ver phishing-quest-api #66). NULL para item legitimo.';

CREATE INDEX idx_phishing_emails_difficulty_estimated ON phishing_emails USING btree (difficulty_estimated);
