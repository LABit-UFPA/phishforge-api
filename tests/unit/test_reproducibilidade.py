"""Hash do commit para o metadata (reprodutibilidade, plano item 5).

O relatorio da comparacao saiu com git_commit=None porque, dentro do
Docker, `git` falha (ausente ou pasta montada em 'dubious ownership'). O
conserto e aceitar a variavel de ambiente GIT_COMMIT como fonte e marcar
'-dirty' quando ha alteracoes nao commitadas.
"""

import app.core.reproducibilidade as repro
from app.core.reproducibilidade import commit_do_git


class _Resultado:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_variavel_de_ambiente_tem_precedencia(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    assert commit_do_git() == "abc1234"


def test_variavel_de_ambiente_e_limpa_de_espacos(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "  def5678  ")
    assert commit_do_git() == "def5678"


def test_variavel_vazia_cai_no_git(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "   ")

    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return _Resultado("ffff999\n")
        return _Resultado("")  # status limpo

    monkeypatch.setattr(repro.subprocess, "run", fake_run)
    assert commit_do_git() == "ffff999"


def test_git_com_alteracoes_marca_dirty(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return _Resultado("abc1234\n")
        if "status" in args:
            return _Resultado(" M app/x.py\n")  # arvore suja
        return _Resultado("", 1)

    monkeypatch.setattr(repro.subprocess, "run", fake_run)
    assert commit_do_git() == "abc1234-dirty"


def test_git_limpo_nao_marca_dirty(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return _Resultado("abc1234\n")
        return _Resultado("")  # status vazio = limpo

    monkeypatch.setattr(repro.subprocess, "run", fake_run)
    assert commit_do_git() == "abc1234"


def test_sem_git_retorna_none(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(repro.subprocess, "run", fake_run)
    assert commit_do_git() is None


def test_git_falha_em_dubious_ownership_retorna_none(monkeypatch):
    """Caso do Docker: `git rev-parse` sai com returncode != 0 (dubious
    ownership). Sem GIT_COMMIT, o resultado e None -- por isso o env é o
    conserto de fato."""
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    def fake_run(args, **kwargs):
        return _Resultado("fatal: detected dubious ownership\n", returncode=128)

    monkeypatch.setattr(repro.subprocess, "run", fake_run)
    assert commit_do_git() is None
