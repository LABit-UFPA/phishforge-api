-- Ficha de variacao por item, relatorio de validacao e log de
-- tentativas do lote (lote-piloto de 26/10/2026).
--
-- O piloto do protocolo de geracao v2 (10 itens, contexto E1-M-A,
-- nivel medio) descartou 5 itens como quase-duplicados, e os 5 aceitos
-- eram o mesmo e-mail com o nome trocado: no lote, contexto,
-- documentos fundidos, prompt e temperatura sao identicos para todos
-- os itens. A correcao sorteia, por item, uma ficha de detalhes
-- (destinatario, quem assina, angulo do pretexto, acao, tom,
-- estrutura, abertura e pistas-alvo) -- ver
-- app/domain/services/variation_sampler.py.
--
-- Todas as colunas sao nullable/default: itens e jobs anteriores a
-- esta migration continuam validos, sem backfill.

ALTER TABLE phishing_emails
    ADD COLUMN target_cues JSONB,
    ADD COLUMN variation_spec JSONB,
    ADD COLUMN validacao JSONB;

COMMENT ON COLUMN phishing_emails.target_cues IS 'Lista de codigos de pista (taxonomia `cues`) que o item DEVERIA conter, sorteada na ficha antes da geracao. Distinta de email_cues (o que o LLM anotou depois de escrever). NULL para item legitimo, item de canal sem ficha ou item anterior a ficha.';
COMMENT ON COLUMN phishing_emails.variation_spec IS 'Ficha de variacao sorteada para o item (VariationSpec): entrada da geracao, guardada para o item ser auditavel e reproduzivel. NULL para itens anteriores a ficha.';
COMMENT ON COLUMN phishing_emails.validacao IS 'Relatorio das validacoes pos-geracao (RelatorioValidacao): evidencias nao literais, pistas removidas (ex.: generic_greeting com nome na saudacao), regeneracoes por marcador de template e aderencia as pistas-alvo.';

ALTER TABLE generation_jobs
    ADD COLUMN attempt_log JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN run_metadata JSONB;

COMMENT ON COLUMN generation_jobs.attempt_log IS 'Uma entrada por tentativa de geracao: {item, nivel, tentativa, similaridade_max, resultado (aceito|repetido|descartado|falha), pistas_alvo}. Inclui as tentativas descartadas pela dedup, que antes nao deixavam rastro.';
COMMENT ON COLUMN generation_jobs.run_metadata IS 'Parametros com que o lote rodou de fato: modelo, temperatura, limiar e retries da dedup, semente das fichas, lotes anteriores usados na dedup e o contexto que o gerador recebeu (generation_context e fused_context, depois da normalizacao).';
