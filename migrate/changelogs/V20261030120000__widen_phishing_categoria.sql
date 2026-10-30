-- A `categoria` vem do LLM como frase descritiva curta. O Sonnet 4.6 (gerador
-- de producao) escreve rotulos de ~45-50 chars (ex.: "Phishing Institucional
-- - Sistema de Matricula", "Institucional Academico - Pendencia de Matricula"),
-- estourando o VARCHAR(50) original: no 1o lote real, 4 de 16 itens falharam na
-- gravacao com "value too long for type character varying(50)". A categoria e
-- so um rotulo, nao um campo restrito -- VARCHAR(255) da folga de sobra.
ALTER TABLE phishing_emails ALTER COLUMN categoria TYPE VARCHAR(255);
