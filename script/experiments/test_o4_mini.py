#!/usr/bin/env python3
"""
Script de teste para entender o comportamento do modelo o4-mini.
"""

import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import settings

# Configura a API key
if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


def test_model(model_name: str, temperature: float = None):
    """Testa um modelo com configurações específicas."""
    print(f"\n{'=' * 50}")
    print(f"Testando modelo: {model_name}")
    print(f"Temperature: {temperature}")
    print(f"{'=' * 50}")

    try:
        # Modelos de reasoning (o1, o3, o4) não suportam temperature
        if temperature is not None:
            model = ChatOpenAI(model=model_name, temperature=temperature)
        else:
            # Sem passar temperature, usa o default do modelo
            model = ChatOpenAI(model=model_name)

        prompt_template = ChatPromptTemplate(
            [
                ("system", "Você é um assistente útil"),
                ("user", "Conte-me uma piada curta sobre {topic}"),
            ]
        )

        prompt = prompt_template.invoke({"topic": "gatos"})
        response = model.invoke(prompt)

        print("✅ Sucesso!")
        print(f"Resposta: {response.content}")
        return True

    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def main():
    print("\n🔬 TESTE DE MODELOS LLM\n")

    # Teste 1: o4-mini com temperature=0.0 (deve falhar)
    print("\n--- Teste 1: o4-mini com temperature=0.0 ---")
    test_model("o4-mini", temperature=0.0)

    # Teste 2: o4-mini com temperature=1.0 (pode funcionar)
    print("\n--- Teste 2: o4-mini com temperature=1.0 ---")
    test_model("o4-mini", temperature=1.0)

    # Teste 3: o4-mini sem temperature (usa default)
    print("\n--- Teste 3: o4-mini sem temperature ---")
    test_model("o4-mini", temperature=None)

    # Teste 4: gpt-4o-mini com temperature=0.7 (deve funcionar)
    print("\n--- Teste 4: gpt-4o-mini com temperature=0.7 ---")
    test_model("gpt-4o-mini", temperature=0.7)

    # Teste 5: gpt-4o-mini sem temperature
    print("\n--- Teste 5: gpt-4o-mini sem temperature ---")
    test_model("gpt-4o-mini", temperature=None)


if __name__ == "__main__":
    main()
