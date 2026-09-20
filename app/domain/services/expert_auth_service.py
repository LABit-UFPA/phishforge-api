import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple
from uuid import UUID

import jwt

# Sem caracteres ambiguos (0/O, 1/I/L): o codigo e lido por um humano
# num e-mail e digitado ou colado. 31 simbolos x 16 posicoes ~ 79 bits,
# gerados por `secrets` (nao escolhidos por humano) -- forca bruta
# inviavel, o que justifica SHA-256 em vez de bcrypt (ver migration).
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_GRUPOS = 4
_TAMANHO_GRUPO = 4
_FORMATO = re.compile(r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")


class ExpertAuthError(Exception):
    """Token ausente, malformado, expirado ou assinado com outro segredo."""


class ExpertAuthService:
    """Codigo de acesso e JWT de sessao do especialista (issue #36).

    `jwt_secret` vazio = servico NAO configurado: quem chama deve
    responder 503 (fail-closed). Nao existe segredo default.
    """

    def __init__(self, jwt_secret: str, expires_hours: int = 12):
        self._secret = jwt_secret
        self._expires_hours = expires_hours

    @property
    def configurado(self) -> bool:
        return bool(self._secret)

    # ---- codigo de acesso -------------------------------------------------

    @staticmethod
    def gerar_codigo() -> str:
        grupos = [
            "".join(secrets.choice(_ALFABETO) for _ in range(_TAMANHO_GRUPO))
            for _ in range(_GRUPOS)
        ]
        return "-".join(grupos)

    @staticmethod
    def normalizar_codigo(codigo: str) -> str:
        """Maiuscula e sem espacos. Devolve o codigo no formato
        canonico se estiver bem formado; senao, o texto normalizado
        assim mesmo (o hash dele simplesmente nao vai bater com nada).
        """
        limpo = re.sub(r"\s+", "", codigo).upper()
        if not _FORMATO.match(limpo):
            compacto = limpo.replace("-", "")
            if len(compacto) == _GRUPOS * _TAMANHO_GRUPO and compacto.isalnum():
                return "-".join(
                    compacto[i : i + _TAMANHO_GRUPO]
                    for i in range(0, len(compacto), _TAMANHO_GRUPO)
                )
        return limpo

    @classmethod
    def hash_codigo(cls, codigo: str) -> str:
        return hashlib.sha256(cls.normalizar_codigo(codigo).encode("utf-8")).hexdigest()

    @classmethod
    def prefixo_codigo(cls, codigo: str) -> str:
        return cls.normalizar_codigo(codigo)[:4]

    # ---- JWT --------------------------------------------------------------

    def emitir_token(self, especialista_id: UUID) -> Tuple[str, datetime]:
        agora = datetime.now(timezone.utc)
        expira = agora + timedelta(hours=self._expires_hours)
        token = jwt.encode(
            {"sub": str(especialista_id), "iat": agora, "exp": expira},
            self._secret,
            algorithm="HS256",
        )
        return token, expira

    def validar_token(self, token: str) -> UUID:
        try:
            payload = jwt.decode(token, self._secret, algorithms=["HS256"])
            return UUID(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as e:
            raise ExpertAuthError("Token invalido ou expirado.") from e
