"""Lista de negacao de instituicoes reais (preparacao do lote-piloto 3).

O 3o teste local (27/10/2026, versao 2026-10-27-piloto3) gerou itens com
dominios da UFRJ (`educacao.ufrj.br`, `ufrj.edu.br`) num cenario que so
dizia "universidade federal brasileira": o prompt pede organizacao
ficticia, mas nada conferia. Golpe simulado em nome de instituicao real
e problema etico do corpus, nao so de estilo.

Usada por `item_validation.encontrar_instituicoes_reais`: item com
qualquer termo daqui no remetente, destinatario, assunto, corpo ou links
e gerado de novo. A lista NAO e exaustiva -- cobre as instituicoes que os
cenarios do protocolo (universidade, banco, orgao publico, varejo,
telecom) tendem a evocar. Ampliar e so acrescentar termos.

Termos em minusculas e sem acento: a busca roda sobre o texto
normalizado (ver `item_validation._normalizar`), com fronteira de
palavra em que ponto, arroba, hifen e sublinhado separam -- entao
"ufrj" casa com "UFRJ", "@ufrj.edu.br" e "ufrj-portal.com".

Ficaram de fora, de proposito:
- Nomes que sao palavras comuns em portugues ("Claro", "Vivo", "Oi",
  "Caixa", "Inter", "Americanas", "Telefonica", e a sigla UNIR, que e o
  verbo "unir"): so contam na forma composta ("Banco Inter", "Lojas
  Americanas") ou como dominio ("claro.com.br").
- Provedores de webmail (gmail.com, outlook.com, hotmail.com): remetente
  @gmail.com e o padrao do nivel facil, nao imitacao de instituicao.
- Plataformas citadas como canal ("pelo WhatsApp", "no Google Meet"):
  mencionar o canal nao e se passar pela empresa.
"""

# Siglas de universidades e institutos (o dominio delas comeca pela sigla,
# entao a mesma entrada pega o texto e o endereco).
SIGLAS_DE_ENSINO = (
    "ufpa", "ufra", "ufopa", "uepa", "ifpa", "unifap",
    "ufrj", "uerj", "ufrrj", "uff", "usp", "unicamp", "unesp", "unifesp",
    "ufscar", "ufabc", "ufmg", "ufjf", "ufv", "ufla", "ufu", "ufop",
    "ufrgs", "ufsm", "ufpel", "ufsc", "ufpr", "utfpr", "unb", "ufg",
    "ufes", "ufba", "ufpe", "ufc", "ufrn", "ufpb", "ufal", "ufma", "ufpi",
    "ufam", "ufms", "ufmt", "ufs", "ufrr", "ufac", "uft",
    "univesp", "uneb", "uefs", "uece", "uern", "uepb", "unimontes",
    "puc", "pucsp", "pucrs", "pucpr", "pucminas", "mackenzie", "fgv", "insper",
)

# Nomes compostos e marcas (sem acento, minusculas). Formas coladas
# ("bancodobrasil") pegam os dominios de imitacao ("bancodobrasil-seguro.com").
NOMES_DE_INSTITUICOES = (
    # bancos e pagamentos
    "banco do brasil", "bancodobrasil", "caixa economica", "caixaeconomica",
    "itau", "bradesco", "santander", "nubank", "banco inter", "bancointer",
    "c6 bank", "c6bank", "btg pactual", "sicredi", "sicoob", "banrisul",
    "banco pan", "banco original", "picpay", "mercado pago", "mercadopago",
    "pagbank", "pagseguro",
    # orgaos publicos e servicos
    "receita federal", "receitafederal", "policia federal", "policiafederal",
    "inss", "detran", "correios", "serasa", "capes", "cnpq",
    "ministerio da educacao", "ministerio da saude",
    # varejo e servicos digitais
    "mercado livre", "mercadolivre", "magazine luiza", "magazineluiza", "magalu",
    "lojas americanas", "americanas.com", "casas bahia", "casasbahia", "shopee", "aliexpress", "amazon",
    "netflix", "paypal", "ifood",
    # telecom (o nome sozinho e palavra comum; so com qualificador)
    "operadora vivo", "operadora claro", "operadora oi", "telefonica vivo",
    # universidades por extenso que nao seguem o padrao estado (ver abaixo)
    "universidade federal fluminense", "universidade estadual paulista",
    "universidade estadual de campinas", "pontificia universidade catolica",
)

# Siglas que, em minusculas, colidem com palavras ou nomes: so contam em
# maiusculas, como sigla.
SIGLAS_SO_EM_MAIUSCULAS = ("TIM", "SUS", "MEC", "ITA")

# Dominios reais cuja parte inicial nao esta acima (ou e palavra comum).
DOMINIOS_REAIS = (
    "gov.br", "bb.com.br", "vivo.com.br", "claro.com.br", "oi.com.br",
    "tim.com.br", "ita.br",
)

# "Universidade Federal do Para", "Universidade de Sao Paulo", "Instituto
# Federal do Para": instituicao publica nomeada pelo estado e real.
ESTADOS = (
    "acre", "alagoas", "amapa", "amazonas", "bahia", "ceara", "distrito federal",
    "espirito santo", "goias", "maranhao", "mato grosso do sul", "mato grosso",
    "minas gerais", "paraiba", "parana", "para", "pernambuco", "piaui",
    "rio de janeiro", "rio grande do norte", "rio grande do sul", "rondonia",
    "roraima", "santa catarina", "sao paulo", "sergipe", "tocantins", "brasilia",
)
