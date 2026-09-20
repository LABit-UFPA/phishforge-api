-- Taxonomia de pistas para uso HUMANO (issue #35).
--
-- A tabela `cues` (V20260919090000, issue #5) nasceu para resolver
-- code -> cue_id na persistencia das anotacoes do LLM, e so tem
-- `label_pt`, um rotulo curto de exibicao. O modulo de avaliacao por
-- especialistas mostra as 10 pistas a um anotador humano no momento
-- de marcar um trecho suspeito: se dois anotadores leem a mesma
-- definicao vaga e decidem diferente, a concordancia entre eles
-- (Cohen's kappa, a metrica central do modulo) mede ambiguidade de
-- instrucao, nao discordancia real de julgamento. Por isso cada pista
-- ganha uma definicao operacional (`descricao_pt`).
--
-- `ativo` permite tirar uma pista do vocabulario de anotacao sem
-- apagar historico: email_cues (e, no futuro, avaliacao_anotacoes)
-- referenciam cues(id) com ON DELETE RESTRICT, entao DELETE nunca foi
-- opcao -- a pista desativada some so das listagens novas.
--
-- ALTER TABLE, nao CREATE TABLE: os 10 UUIDs literais espelhados do
-- backend Go ja estao semeados desde a #5 e NAO podem ser recriados.

ALTER TABLE cues
    ADD COLUMN descricao_pt TEXT,
    ADD COLUMN ativo BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE cues SET descricao_pt = 'O dominio do remetente exibido nao corresponde ao dominio oficial da organizacao que a mensagem alega representar (ex.: nome da empresa no texto, mas dominio de e-mail generico ou de terceiros).' WHERE code = 'sender_domain_mismatch';
UPDATE cues SET descricao_pt = 'Dominio com um ou mais caracteres trocados, adicionados ou removidos de proposito para parecer o dominio oficial (ex.: banc0-brasil.com em vez de bancodobrasil.com.br).' WHERE code = 'typosquat';
UPDATE cues SET descricao_pt = 'Caractere visualmente identico ou muito parecido substituido no dominio ou no texto para enganar a leitura rapida (ex.: "rn" no lugar de "m", "l" minusculo no lugar de "I" maiusculo).' WHERE code = 'homoglyph';
UPDATE cues SET descricao_pt = 'Apelo a agir rapidamente, com prazo curto ou consequencia iminente, que pressiona a vitima a nao verificar antes de agir.' WHERE code = 'urgency';
UPDATE cues SET descricao_pt = 'Apelo a autoridade de uma figura ou instituicao (banco, governo, chefia, TI interna) para induzir obediencia sem questionamento.' WHERE code = 'authority';
UPDATE cues SET descricao_pt = 'Saudacao impessoal, sem usar o nome do destinatario (ex.: "Prezado cliente", "Caro usuario"), quando seria esperado tratamento nominal numa comunicacao legitima daquele tipo.' WHERE code = 'generic_greeting';
UPDATE cues SET descricao_pt = 'Solicitacao direta de senha, codigo de verificacao, dado de cartao ou outro segredo de autenticacao.' WHERE code = 'credential_request';
UPDATE cues SET descricao_pt = 'O texto exibido do link sugere um destino diferente do endereco real para onde ele aponta.' WHERE code = 'link_text_mismatch';
UPDATE cues SET descricao_pt = 'Anexo presente sem justificativa clara no contexto da mensagem, ou de tipo incomum para o que esta sendo descrito.' WHERE code = 'unexpected_attachment';
UPDATE cues SET descricao_pt = 'Apelo a escassez ou oferta por tempo/quantidade limitada, usado para induzir acao impulsiva.' WHERE code = 'scarcity';

-- Toda pista da taxonomia canonica precisa ter definicao: uma linha
-- sem descricao_pt mostraria um popover vazio ao especialista.
ALTER TABLE cues ALTER COLUMN descricao_pt SET NOT NULL;

COMMENT ON COLUMN cues.descricao_pt IS 'Definicao operacional da pista, mostrada ao anotador humano (issue #35). Escrita para dois anotadores chegarem a mesma decisao dado o mesmo trecho -- diferente de label_pt, que e so um rotulo curto de exibicao.';
COMMENT ON COLUMN cues.ativo IS 'FALSE tira a pista das listagens novas sem apagar historico: email_cues/avaliacao_anotacoes que ja referenciam este cue_id continuam validos via FK.';
