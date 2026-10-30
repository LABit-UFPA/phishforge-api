"""Identificacao do codigo que gerou um lote/rodada (reprodutibilidade).

O hash do commit entra no metadata do relatorio de comparacao (ver
script/avaliar_modelos_llm.py) e no run_metadata de cada lote de producao
(ver batch_generation_worker.py): se o gerador mudou, tem de constar.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

# Raiz do repo -- este arquivo esta em app/core/.
_RAIZ = Path(__file__).resolve().parent.parent.parent


def commit_do_git() -> Optional[str]:
    """Hash curto do commit atual, com sufixo '-dirty' quando ha alteracoes
    nao commitadas. Fontes, em ordem:

    1. Variavel de ambiente GIT_COMMIT -- o caminho de dentro do Docker, onde
       `git` pode faltar ou a pasta montada cair em 'dubious ownership' (foi
       assim que o relatorio da comparacao saiu com git_commit=None). O docker
       run passa `-e GIT_COMMIT=$(git rev-parse --short HEAD)`.
    2. `git` de fato, no repo (fora do Docker).

    None so quando nenhuma das duas resolve. Best-effort -- nunca levanta,
    para nao derrubar a gravacao do relatorio/lote por falta de git.
    """
    env = os.environ.get("GIT_COMMIT", "").strip()
    if env:
        return env

    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", str(_RAIZ), *args],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        return None
    if _git("status", "--porcelain"):
        commit += "-dirty"
    return commit
