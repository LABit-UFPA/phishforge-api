"""Ficha de variacao por item (lote-piloto de 26/10/2026): o sorteio
precisa respeitar as regras de cada nivel do prompt e cobrir os valores
de forma balanceada dentro de um lote.
"""

import random
from collections import Counter
from itertools import combinations

import pytest

from app.domain.models.cue import CueCode
from app.domain.services.instituicoes_ficticias import INSTITUICOES
from app.domain.services.item_validation import (
    encontrar_dominios_caricatos,
    encontrar_marcadores,
)
from app.domain.services.variation_sampler import (
    ACAO_ANEXO,
    ACOES_COM_LINK,
    ACOES_SEM_LINK,
    ASSINATURA_PESSOA,
    COMO_REALIZAR,
    ENDERECO_LIVRE,
    ESTILOS_DE_ASSUNTO,
    ESTRUTURAS_COMPLETAS,
    PISTA_FIXA_FACIL,
    POOL_DIFICIL,
    POOL_FACIL,
    POOL_MEDIO,
    TIPOS_DESTINATARIO,
    WEBMAILS,
    VariationSampler,
    gerar_typosquat,
    renderizar_ficha,
)


def _sampler(seed=7):
    return VariationSampler(random.Random(seed))


def test_medio_tem_exatamente_duas_pistas_com_nome_e_sem_link():
    sampler = _sampler()
    for _ in range(50):
        ficha = sampler.sortear("medio")
        assert len(ficha.pistas_alvo) == 2
        assert len(set(ficha.pistas_alvo)) == 2
        assert all(p in POOL_MEDIO for p in ficha.pistas_alvo)
        # Nome na saudacao: generic_greeting nunca e alvo no medio.
        assert CueCode.GENERIC_GREETING not in ficha.pistas_alvo
        assert ficha.nome_destinatario
        # MEDIO nunca tem link (issue #20).
        assert ficha.acao in ACOES_SEM_LINK
        assert ficha.estrutura in ESTRUTURAS_COMPLETAS


def test_medio_com_pista_de_anexo_pede_acao_de_anexo():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(60)]
    com_anexo = [f for f in fichas if CueCode.UNEXPECTED_ATTACHMENT in f.pistas_alvo]
    assert com_anexo
    assert all(f.acao == ACAO_ANEXO for f in com_anexo)


def test_facil_tem_saudacao_generica_fixa_e_sem_nome():
    sampler = _sampler()
    for _ in range(30):
        ficha = sampler.sortear("facil")
        assert len(ficha.pistas_alvo) == 3
        assert ficha.pistas_alvo[0] == CueCode.GENERIC_GREETING
        assert ficha.nome_destinatario is None
        assert ficha.acao in ACOES_COM_LINK


def test_dificil_tem_uma_pista_so_que_o_link_consome():
    sampler = _sampler()
    for _ in range(20):
        ficha = sampler.sortear("dificil")
        assert len(ficha.pistas_alvo) == 1
        assert ficha.pistas_alvo[0] in POOL_DIFICIL
        assert ficha.nome_destinatario
        assert ficha.acao in ACOES_COM_LINK


def test_item_legitimo_nao_tem_pista_nem_acao_e_tem_nome():
    ficha = _sampler().sortear("medio", is_malicious=False)
    assert ficha.pistas_alvo == []
    assert ficha.acao is None
    assert ficha.nome_destinatario


def test_pares_de_pistas_do_medio_cobrem_o_pool_de_forma_balanceada():
    """21 pares possiveis no medio: em 42 itens, cada par sai exatamente
    2 vezes -- e o que o sorteio por ciclo garante, e o que um sorteio
    independente nao garantiria.
    """
    sampler = _sampler()
    pares = Counter(
        frozenset(sampler.sortear("medio").pistas_alvo) for _ in range(42)
    )
    todos = {frozenset(par) for par in combinations(POOL_MEDIO, 2)}
    assert set(pares) == todos
    assert set(pares.values()) == {2}


def test_mesma_semente_reproduz_as_mesmas_fichas():
    sampler_a, sampler_b = _sampler(123), _sampler(123)
    a = [sampler_a.sortear(n) for n in ("facil", "medio", "dificil") * 5]
    b = [sampler_b.sortear(n) for n in ("facil", "medio", "dificil") * 5]
    assert a == b


def test_fichas_seguidas_do_mesmo_nivel_variam():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(10)]
    assert len({f.nome_destinatario for f in fichas}) == 10
    assert len({f.angulo_pretexto for f in fichas}) > 1
    assert len({f.abertura for f in fichas}) > 1


def test_nomes_padrao_do_modelo_ficam_fora_do_sorteio():
    """'Joao', 'Maria' e 'Silva' eram os nomes que o modelo usava sozinho
    no piloto: fora do sorteio, um item que volte com eles denuncia que a
    ficha foi ignorada.
    """
    sampler = _sampler()
    palavras = {
        palavra
        for _ in range(200)
        for palavra in sampler.sortear("medio").nome_destinatario.split()
    }
    assert not palavras & {"João", "Joao", "Maria", "Silva"}


def test_dificuldade_fora_do_vocabulario_falha_alto():
    with pytest.raises(ValueError):
        _sampler().sortear("Médio")


def test_renderizar_ficha_traz_nome_pistas_e_acao():
    ficha = _sampler().sortear("medio")
    texto = renderizar_ficha(ficha)
    assert ficha.nome_destinatario in texto
    assert ficha.acao in texto
    for pista in ficha.pistas_alvo:
        assert f"`{pista.value}`" in texto


def test_renderizar_ficha_sem_nome_pede_saudacao_generica():
    texto = renderizar_ficha(_sampler().sortear("facil"))
    assert "saudação deve ser genérica" in texto


def test_renderizar_sem_ficha_devolve_instrucao_de_escolha_livre():
    assert "Nenhuma ficha" in renderizar_ficha(None)


# ---------------------------------------------------------------------------
# Lote-piloto 2 (27/10/2026)
# ---------------------------------------------------------------------------


def test_estilo_do_assunto_varia_dentro_do_lote():
    """Piloto 2: os 9 assuntos comecavam com 'Acao Necessaria:'."""
    sampler = _sampler()
    estilos = [sampler.sortear("medio").estilo_assunto for _ in range(len(ESTILOS_DE_ASSUNTO))]
    assert set(estilos) == set(ESTILOS_DE_ASSUNTO)


def test_nome_de_quem_assina_so_quando_a_assinatura_e_uma_pessoa():
    sampler = _sampler()
    for _ in range(20):
        ficha = sampler.sortear("medio")
        if ficha.assinatura == ASSINATURA_PESSOA:
            assert ficha.nome_remetente and ficha.nome_remetente != ficha.nome_destinatario
        else:
            assert ficha.nome_remetente is None


def test_endereco_do_remetente_segue_as_pistas_alvo_do_medio():
    sampler = _sampler()
    for _ in range(42):
        ficha = sampler.sortear("medio")
        dominio_oficial = ficha.instituicao.dominio_oficial
        if CueCode.SENDER_DOMAIN_MISMATCH in ficha.pistas_alvo:
            assert ficha.dominio_da_pista_em == "remetente"
            assert ficha.dominio_da_pista in WEBMAILS
            assert dominio_oficial not in ficha.endereco_remetente
        elif CueCode.TYPOSQUAT in ficha.pistas_alvo:
            assert ficha.dominio_da_pista_em == "remetente"
            assert ficha.dominio_da_pista != dominio_oficial
            assert ficha.dominio_da_pista in ficha.endereco_remetente
        else:
            assert ficha.dominio_da_pista is None
            assert dominio_oficial in ficha.endereco_remetente


def test_dificil_mantem_o_orcamento_de_uma_pista():
    sampler = _sampler()
    for _ in range(20):
        ficha = sampler.sortear("dificil")
        if ficha.pistas_alvo == [CueCode.TYPOSQUAT]:
            # O typosquat vai no link obrigatorio; o remetente fica plausivel.
            assert ficha.dominio_da_pista_em == "link"
            assert ficha.instituicao.dominio_oficial in ficha.endereco_remetente
            assert ficha.dominio_da_pista != ficha.instituicao.dominio_oficial
        else:
            assert ficha.pistas_alvo == [CueCode.SENDER_DOMAIN_MISMATCH]
            assert ficha.dominio_da_pista_em == "remetente_e_link"
            assert "link obrigatório aponta para esse mesmo domínio" in ficha.endereco_remetente
            assert ficha.dominio_da_pista in ficha.endereco_remetente


def test_facil_sem_pista_de_dominio_deixa_o_remetente_livre():
    sampler = _sampler()
    for _ in range(21):
        ficha = sampler.sortear("facil")
        if not {CueCode.SENDER_DOMAIN_MISMATCH, CueCode.TYPOSQUAT} & set(ficha.pistas_alvo):
            assert ficha.endereco_remetente == ENDERECO_LIVRE


def test_ficha_renderizada_diz_como_realizar_cada_pista_alvo():
    ficha = _sampler().sortear("medio")
    texto = renderizar_ficha(ficha)
    for pista in ficha.pistas_alvo:
        assert f"`{pista.value}`: {COMO_REALIZAR[pista]}" in texto
    assert ficha.estilo_assunto in texto
    assert ficha.endereco_remetente in texto


def test_toda_pista_dos_pools_tem_instrucao_de_como_realizar():
    for pista in {*POOL_MEDIO, *POOL_DIFICIL, *POOL_FACIL, PISTA_FIXA_FACIL}:
        assert COMO_REALIZAR[pista]


def test_scarcity_e_explicada_como_quantidade_e_nao_prazo():
    assert "não é prazo" in COMO_REALIZAR[CueCode.SCARCITY]


# ---------------------------------------------------------------------------
# Lote-piloto 5 (correcoes de qualidade, itens 2.1-2.3)
# ---------------------------------------------------------------------------


def test_instituicao_vem_da_lista_versionada_e_e_balanceada():
    """2.1: cada item sorteia uma instituicao da lista, em ciclo
    balanceado -- mesma garantia que as demais dimensoes da ficha.
    """
    sampler = _sampler()
    instituicoes = [sampler.sortear("medio").instituicao for _ in range(len(INSTITUICOES))]
    assert set(instituicoes) == set(INSTITUICOES)


def test_instituicao_fixa_no_construtor_vale_para_todo_o_lote():
    """2.1: a requisicao do lote pode fixar uma instituicao para a
    celula inteira (BatchGenerationRequest.instituicao) -- o sampler
    deixa de sortear e usa sempre a mesma.
    """
    fixa = INSTITUICOES[3]
    sampler = VariationSampler(random.Random(7), instituicao=fixa)
    for _ in range(10):
        assert sampler.sortear("facil").instituicao == fixa
        assert sampler.sortear("medio", is_malicious=False).instituicao == fixa


def test_gerar_typosquat_nunca_repete_o_dominio_oficial():
    for instituicao in INSTITUICOES:
        # So o primeiro rotulo muda (ver gerar_typosquat): o sufixo
        # (".com.br", ".org.br", ".net.br", ".com" -- a lista tem os
        # quatro) fica igual ao do dominio oficial.
        _, _, sufixo_oficial = instituicao.dominio_oficial.partition(".")
        for seed in range(100):
            typo = gerar_typosquat(instituicao.dominio_oficial, random.Random(seed))
            assert typo != instituicao.dominio_oficial
            assert typo.endswith(f".{sufixo_oficial}")
            assert encontrar_dominios_caricatos(typo) == []


def test_gerar_typosquat_e_reproduzivel_com_a_mesma_semente():
    a = gerar_typosquat("vallonta.com.br", random.Random(42))
    b = gerar_typosquat("vallonta.com.br", random.Random(42))
    assert a == b


def test_sender_domain_mismatch_usa_webmail_em_facil_e_medio():
    sampler = _sampler()
    for nivel in ("facil", "medio"):
        fichas = [sampler.sortear(nivel) for _ in range(60)]
        com_mismatch = [f for f in fichas if CueCode.SENDER_DOMAIN_MISMATCH in f.pistas_alvo]
        assert com_mismatch
        assert all(f.dominio_da_pista in WEBMAILS for f in com_mismatch)


def test_sender_domain_mismatch_usa_outra_instituicao_no_dificil():
    sampler = _sampler()
    fichas = [sampler.sortear("dificil") for _ in range(20)]
    com_mismatch = [f for f in fichas if f.pistas_alvo == [CueCode.SENDER_DOMAIN_MISMATCH]]
    assert com_mismatch
    for ficha in com_mismatch:
        assert ficha.dominio_da_pista not in WEBMAILS
        assert ficha.dominio_da_pista != ficha.instituicao.dominio_oficial
        assert ficha.dominio_da_pista in {i.dominio_oficial for i in INSTITUICOES}


def test_endereco_destinatario_institucional_usa_o_dominio_da_organizacao():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(40)]
    institucionais = [
        f for f in fichas if f.endereco_destinatario.endswith(f"@{f.instituicao.dominio_oficial}")
    ]
    pessoais = [f for f in fichas if f.endereco_destinatario.split("@")[1] in WEBMAILS]
    assert institucionais and pessoais


def test_endereco_destinatario_usa_o_nome_normalizado_quando_ha_nome():
    import unicodedata

    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(10)]
    for ficha in fichas:
        assert ficha.nome_destinatario
        usuario, _, _dominio = ficha.endereco_destinatario.partition("@")
        sem_acento = unicodedata.normalize("NFKD", ficha.nome_destinatario)
        sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
        esperado = ".".join(sem_acento.lower().split())
        assert usuario == esperado


def test_endereco_destinatario_sem_nome_nunca_e_um_marcador():
    """Facil (saudacao generica, sem nome): o endereco nao pode virar um
    placeholder como "aluno@..." que o proprio validador de marcador
    reconheceria -- aqui simplesmente nao ha "nome" nenhum para virar
    marcador, so um contato numerado.
    """
    sampler = _sampler()
    for _ in range(10):
        ficha = sampler.sortear("facil")
        assert ficha.nome_destinatario is None
        usuario = ficha.endereco_destinatario.split("@")[0]
        assert usuario.startswith("contato")
        assert encontrar_marcadores(ficha.endereco_destinatario) == []


def test_destinatario_tipo_e_balanceado_dentro_do_lote():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(len(TIPOS_DESTINATARIO) * 2)]
    institucional = sum(
        1 for f in fichas if f.endereco_destinatario.endswith(f.instituicao.dominio_oficial)
    )
    pessoal = sum(1 for f in fichas if f.endereco_destinatario.split("@")[1] in WEBMAILS)
    assert institucional == 2 and pessoal == 2


def test_renderizar_ficha_traz_a_identidade_da_organizacao():
    ficha = _sampler().sortear("medio")
    texto = renderizar_ficha(ficha)
    assert ficha.instituicao.nome_base in texto
    assert ficha.instituicao.sigla in texto
    assert ficha.instituicao.dominio_oficial in texto
    assert ficha.endereco_destinatario in texto


def test_renderizar_ficha_mostra_o_dominio_da_pista_quando_houver():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(42)]
    com_dominio = [f for f in fichas if f.dominio_da_pista]
    assert com_dominio
    for ficha in com_dominio:
        texto = renderizar_ficha(ficha)
        assert f"`{ficha.dominio_da_pista}`" in texto


def test_item_legitimo_tambem_tem_instituicao_e_endereco_de_destinatario():
    ficha = _sampler().sortear("medio", is_malicious=False)
    assert ficha.instituicao in INSTITUICOES
    assert "@" in ficha.endereco_destinatario
    assert ficha.dominio_da_pista is None
