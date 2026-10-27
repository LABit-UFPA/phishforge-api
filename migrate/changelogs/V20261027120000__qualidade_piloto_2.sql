-- Correcoes de qualidade do 2o lote-piloto (27/10/2026).
--
-- 1. email_cues.campo: em que parte do item a evidencia da pista esta
--    (conteudo, assunto ou remetente), o mesmo vocabulario do `campo`
--    das anotacoes dos especialistas (avaliacao_anotacoes). Antes os
--    spans so eram calculados sobre o conteudo, e pistas no remetente
--    (sender_domain_mismatch) ficavam sem posicao -- 2 dos 4 spans vazios
--    do piloto. NULL nas linhas anteriores (span relativo ao conteudo).
--
-- 2. Definicoes de urgency e scarcity: a de scarcity dizia "oferta por
--    tempo/quantidade limitada", o que tambem cobre um prazo, e o piloto
--    teve "ate o final da semana" anotado como scarcity. As duas passam a
--    separar tempo (urgency) de quantidade ou oferta limitada (scarcity).
--    E o texto que o especialista ve no popover de anotacao E o que o
--    anotador as cegas do LLM usa (DEFINICOES_OPERACIONAIS em
--    app/domain/models/cue.py) -- os dois precisam continuar identicos.

ALTER TABLE email_cues
    ADD COLUMN campo VARCHAR(16)
        CHECK (campo IN ('conteudo', 'assunto', 'remetente'));

COMMENT ON COLUMN email_cues.campo IS 'Campo do item em que span_start/span_end se aplicam (conteudo, assunto ou remetente) -- mesmo vocabulario de avaliacao_anotacoes.campo. NULL em pistas anteriores a esta coluna (span relativo ao conteudo) ou sem evidencia localizada.';

UPDATE cues SET descricao_pt = 'Apelo a agir rapidamente, com prazo curto ou consequencia iminente, que pressiona a vitima a nao verificar antes de agir. Inclui prazo para cumprir uma obrigacao ou evitar uma sancao (ex.: "regularize ate sexta-feira").' WHERE code = 'urgency';
UPDATE cues SET descricao_pt = 'Apelo a escassez: oferta, vaga ou beneficio limitado em quantidade, ou disponivel so por tempo limitado (ex.: "restam 3 vagas", "so para os 50 primeiros", "promocao valida hoje"), usado para induzir acao impulsiva. Prazo para cumprir uma obrigacao e urgency, nao scarcity.' WHERE code = 'scarcity';
