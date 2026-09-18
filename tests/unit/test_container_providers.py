"""Prova de que reranker, response_generator, prompt_normalizer e
user_answer_evaluator sao providers.Singleton, nao providers.Factory
(issue #12).

Checa o TIPO do provider (`isinstance(container.reranker,
providers.Singleton)`), sem resolve-lo (sem chamar `container.
reranker()`): resolver de verdade construiria o cross-encoder real
(download de modelo) e clientes ChatOpenAI, exatamente o que a suite
unitaria existe para evitar. Acessar o atributo do provider sem
invoca-lo (sem os parenteses) nao constroi nada -- confirmado
experimentalmente antes de escrever este teste.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-nao-usada-em-nenhuma-chamada-real")

from dependency_injector import providers

from app.core.container import Container


def test_reranker_e_singleton():
    container = Container()
    assert isinstance(container.reranker, providers.Singleton)


def test_response_generator_e_singleton():
    container = Container()
    assert isinstance(container.response_generator, providers.Singleton)


def test_prompt_normalizer_e_singleton():
    container = Container()
    assert isinstance(container.prompt_normalizer, providers.Singleton)


def test_user_answer_evaluator_e_singleton():
    container = Container()
    assert isinstance(container.user_answer_evaluator, providers.Singleton)


def test_embedding_service_e_embedding_client_st_nao_existem_mais():
    """Fiacao morta removida (issue #12): os dois providers nao devem
    mais existir no container.
    """
    container = Container()
    assert not hasattr(container, "embedding_service")
    assert not hasattr(container, "embedding_client_st")
