from typing import List, Optional
from uuid import UUID
from app.domain.models.phishing_email import PhishingEmail
from app.infra.database.repositories.analytics_repository import AnalyticsRepository
from app.infra.database.repositories.phishing_repository import PhishingEmailRepository

# Vocabulario canonico persistido em phishing_emails.nivel (CHECK
# phishing_emails_nivel_check, migration V20260517120000). Nao importa
# app.domain.models.difficulty.Difficulty aqui de proposito: aquele
# enum e para VALIDAR entrada na borda da API (issue #2), este e so
# para o filtro de busca de list_emails aceitar sinonimo de nivel --
# duas preocupacoes diferentes que nao precisam compartilhar tipo.
_NIVEL_SEARCH_SYNONYMS = {
    'facil': 'facil',
    'medio': 'medio',
    'dificil': 'dificil',
    'fácil': 'facil',
    'médio': 'medio',
    'difícil': 'dificil',
    'easy': 'facil',
    'medium': 'medio',
    'hard': 'dificil',
}


class PhishingEmailService:
    def __init__(self, repository: PhishingEmailRepository, analytics_repository: AnalyticsRepository):
        self.repository = repository
        self.analytics_repository = analytics_repository

    async def create_email(self, email: PhishingEmail) -> UUID:
        """Cria um novo email de phishing e sua análise.

        `email.nivel` chega aqui já validado e normalizado pelo
        endpoint (`QueryRequest`/`BatchGenerationRequest`, tipados por
        `Difficulty` -- ver issue #2): deve sempre ser um dos três
        valores canônicos. Antes desta correção, um valor fora do
        vocabulário era silenciosamente rebaixado para 'medio' aqui
        dentro (`level_mapping`, com um `print()` de aviso que nenhum
        client via). Isso escondia exatamente o tipo de regressão que
        a issue #2 existe para eliminar -- agora é um erro explícito:
        se um valor inválido chega até aqui, a validação de entrada foi
        contornada em algum lugar, e isso precisa aparecer, não ser
        absorvido em silêncio.
        """
        if email.nivel not in ('facil', 'medio', 'dificil'):
            raise ValueError(
                f"nivel invalido chegou ao PhishingEmailService: '{email.nivel}'. "
                "Isso indica que a validacao de entrada foi contornada "
                "antes de chegar aqui -- ver issue #2."
            )

        # Mesma logica de "erro explicito, nao correcao silenciosa" da
        # validacao de nivel acima -- issue #5, passo 9. O primeiro
        # cinto de seguranca e em ResponseGenerator._validar_cues
        # (descarta a pista antes do PhishingEmail existir); este e o
        # segundo, para qualquer chamador que monte um PhishingEmail
        # sem passar pelo gerador.
        if not email.is_malicious and email.cues:
            raise ValueError(
                f"item legitimo chegou ao PhishingEmailService com {len(email.cues)} "
                "pista(s) de phishing anotada(s) -- ver issue #5, passo 9."
            )

        # Salva o email
        email_id = await self.repository.create(email)

        # Computa e salva analytics básicos
        await self._compute_and_save_analytics(email_id, email)

        return email_id

    async def get_email_by_id(self, email_id: UUID) -> Optional[PhishingEmail]:
        """Busca um email por ID"""
        return await self.repository.get_by_id(email_id)

    async def get_emails_by_ids(self, email_ids: List[UUID]) -> List[PhishingEmail]:
        """Busca varios emails na mesma ordem de `email_ids` (issue
        #11b: o endpoint de status do job de lote usa isso).
        """
        return await self.repository.get_by_ids(email_ids)

    async def list_emails(
        self,
        categoria: Optional[str] = None,
        nivel: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[PhishingEmail]:
        """Lista emails; os filtros presentes se combinam com E logico.

        `nivel` aceita sinonimo como conveniencia de busca (ex.:
        `?nivel=easy`) -- diferente da validacao de `create_email`: aqui
        um valor que nao bate com nada so devolve lista vazia, sem risco
        de dado corrompido, entao o fallback (`nivel` cru se nao achar
        sinonimo) e aceitavel.
        """
        if nivel:
            nivel = _NIVEL_SEARCH_SYNONYMS.get(nivel.lower().strip(), nivel)
        return await self.repository.list_emails(categoria, nivel, search, limit, offset)

    async def get_statistics(self) -> dict:
        """Retorna estatísticas dos emails"""
        stats = await self.repository.get_stats()
        return stats
    
    async def delete_email(self, email_id: UUID) -> bool:
        """Deleta um email"""
        return await self.repository.delete(email_id)
    
    async def _compute_and_save_analytics(self, email_id: UUID, email: PhishingEmail):
        """Computa e salva analytics básicos do email"""
        # Palavras suspeitas comuns em phishing
        suspicious_words = [
            'urgente', 'imediatamente', 'clique', 'confirme', 'verifique',
            'premio', 'ganhou', 'suspenso', 'bloqueado', 'expire', 
            'atualizar', 'dados', 'senha', 'cartao', 'conta'
        ]
        
        content_lower = email.conteudo.lower()
        suspicious_count = sum(1 for word in suspicious_words if word in content_lower)
        word_count = len(email.conteudo.split())
        
        metadata = {
            'subject_length': len(email.assunto),
            'content_length': len(email.conteudo),
            'link_count': len(email.links),
            'has_urgency': any(urgent in content_lower for urgent in ['urgente', 'imediatamente', 'agora']),
            'has_verification_request': any(verify in content_lower for verify in ['confirme', 'verifique', 'atualize']),
            'suspicious_words_found': [word for word in suspicious_words if word in content_lower],
            'original_level': email.nivel,  # Guarda o nível original
            'level_mapping_applied': True
        }
        
        await self.analytics_repository.create_analytics(
            email_id=email_id,
            word_count=word_count,
            suspicious_keywords_count=suspicious_count,
            analysis_metadata=metadata
        )