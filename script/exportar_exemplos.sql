-- Exporta os exemplos gerados para CSV, para analise fora do sistema.
--
-- Uso (na pasta phishforge-api, com o compose de pe):
--   docker compose run --rm phishforge-export
-- Os arquivos aparecem em phishforge-api/exports/.
--
-- \copy grava no lado do cliente (o container de export), que monta
-- ./exports -- por isso cada \copy precisa estar numa linha so.

\echo 'Exportando exports/exemplos.csv (um exemplo por linha)...'
\copy (SELECT e.id, e.created_at, e.is_malicious, e.nivel, e.difficulty_estimated, e.phish_scale_cue_count, e.phish_scale_premise_alignment, e.categoria, e.remetente, e.receptor, e.assunto, e.conteudo, e.explicacao, e.links, (SELECT string_agg(c.code, ';' ORDER BY c.code) FROM email_cues ec JOIN cues c ON c.id = ec.cue_id WHERE ec.email_id = e.id) AS pistas, (SELECT string_agg(x, ';' ORDER BY x) FROM jsonb_array_elements_text(e.target_cues) x) AS pistas_alvo, e.variation_spec AS ficha, e.validacao, j.id AS lote_id, j.context AS contexto_lote FROM phishing_emails e LEFT JOIN generation_jobs j ON j.item_ids ? e.id::text WHERE e.channel = 'email' ORDER BY e.created_at) TO '/exports/exemplos.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Exportando exports/pistas.csv (uma pista anotada pelo LLM por linha)...'
\copy (SELECT ec.email_id, c.code AS pista, c.label_pt AS pista_rotulo, c.category AS pista_categoria, ec.evidencia, ec.campo, ec.span_start, ec.span_end FROM email_cues ec JOIN cues c ON c.id = ec.cue_id JOIN phishing_emails e ON e.id = ec.email_id WHERE e.channel = 'email' ORDER BY e.created_at, ec.span_start NULLS LAST) TO '/exports/pistas.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Exportando exports/lotes.csv (um lote por linha, com os parametros com que rodou)...'
\copy (SELECT j.id AS lote_id, j.created_at, j.completed_at, j.status, j.context AS contexto_lote, j.total AS total_pedido, j.total_generated, j.total_discarded, j.total_failed, j.run_metadata->>'versao_gerador' AS versao_gerador, j.run_metadata->>'modelo' AS modelo, j.run_metadata->>'anotacao_cega' AS anotacao_cega, j.run_metadata->>'temperatura' AS temperatura, j.run_metadata->>'seed' AS seed, j.run_metadata->>'limiar_dedup' AS limiar_dedup, j.run_metadata->>'itens_de_lotes_anteriores' AS itens_de_lotes_anteriores, (SELECT string_agg(x, ';') FROM jsonb_array_elements_text(j.run_metadata->'dedup_job_ids') x) AS dedup_job_ids FROM generation_jobs j ORDER BY j.created_at) TO '/exports/lotes.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Exportando exports/tentativas.csv (uma tentativa de geracao por linha, inclusive as descartadas)...'
\copy (SELECT j.id AS lote_id, j.context AS contexto_lote, (t->>'item')::int AS item, t->>'nivel' AS nivel, (t->>'tentativa')::int AS tentativa, (t->>'similaridade_max')::float AS similaridade_max, t->>'resultado' AS resultado, (SELECT string_agg(x, ';' ORDER BY x) FROM jsonb_array_elements_text(t->'pistas_alvo') x) AS pistas_alvo FROM generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(j.attempt_log) t ORDER BY j.created_at, (t->>'item')::int, (t->>'tentativa')::int) TO '/exports/tentativas.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Pronto.'
