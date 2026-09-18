from pydantic import BaseModel
from typing import List

class PhishingEmail(BaseModel):
    receptor: str
    remetente: str
    assunto: str
    conteudo: str
    explicacao: str
    nivel: str
    categoria: str
    links: List[str]
    # Default True preserva o comportamento historico (todo item ate a
    # issue #3 era phishing por construcao) para quem constroi este
    # modelo sem passar o campo explicitamente. O endpoint sempre passa
    # o valor explicito, vindo da request ja validada -- assim como
    # `nivel`, `is_malicious` e entrada da geracao, nunca faz parte do
    # que o LLM emite (ver GeneratedItemDraft e o comentario da #11).
    is_malicious: bool = True