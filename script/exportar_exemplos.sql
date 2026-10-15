-- Exporta os exemplos gerados para CSV, para analise fora do sistema.
--
-- Uso (na pasta phishforge-api, com o compose de pe):
--   docker compose run --rm phishforge-export
-- Os arquivos aparecem em phishforge-api/exports/.
--
-- \copy grava no lado do cliente (o container de export), que monta
-- ./exports -- por isso cada \copy precisa estar numa linha so.

\echo 'Exportando exports/exemplos.csv (um exemplo por linha)...'
\copy (SELECT e.id, e.created_at, e.is_malicious, e.nivel, e.difficulty_estimated, e.phish_scale_cue_count, e.phish_scale_premise_alignment, e.categoria, e.remetente, e.receptor, e.assunto, e.conteudo, e.explicacao, e.links, (SELECT string_agg(c.code, ';' ORDER BY c.code) FROM email_cues ec JOIN cues c ON c.id = ec.cue_id WHERE ec.email_id = e.id) AS pistas, j.id AS lote_id, j.context AS contexto_lote FROM phishing_emails e LEFT JOIN generation_jobs j ON j.item_ids ? e.id::text WHERE e.channel = 'email' ORDER BY e.created_at) TO '/exports/exemplos.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Exportando exports/pistas.csv (uma pista anotada pelo LLM por linha)...'
\copy (SELECT ec.email_id, c.code AS pista, c.label_pt AS pista_rotulo, c.category AS pista_categoria, ec.evidencia, ec.span_start, ec.span_end FROM email_cues ec JOIN cues c ON c.id = ec.cue_id JOIN phishing_emails e ON e.id = ec.email_id WHERE e.channel = 'email' ORDER BY e.created_at, ec.span_start NULLS LAST) TO '/exports/pistas.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8')

\echo 'Pronto.'
