from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from asyncpg import Pool

from app.domain.models.evaluation import (EvaluationMetricsSummary,
                                          EvaluationRetrievedDocument,
                                          EvaluationSession,
                                          EvaluationSessionResult,
                                          RagasEvaluation, RagasMetric,
                                          SessionPerformanceOverview)


class EvaluationRepository:
    """Repository para gerenciar avaliações RAGAS no banco de dados."""
    
    def __init__(self, db_pool: Pool):
        self.db_pool = db_pool
    
    # Métodos para EvaluationSession
    
    async def create_session(self, session: EvaluationSession) -> UUID:
        """Cria uma nova sessão de avaliação."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO evaluation_sessions (session_name, description, status)
                VALUES ($1, $2, $3)
                RETURNING id
            """, session.session_name, session.description, session.status)
            return row['id']
    
    async def get_session_by_id(self, session_id: UUID) -> Optional[EvaluationSession]:
        """Busca uma sessão por ID."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM evaluation_sessions WHERE id = $1
            """, session_id)
            
            if row:
                return EvaluationSession(**dict(row))
            return None
    
    async def update_session_status(self, session_id: UUID, status: str, 
                                   completed_at: Optional[datetime] = None) -> bool:
        """Atualiza o status de uma sessão."""
        async with self.db_pool.acquire() as conn:
            if completed_at and status == 'completed':
                result = await conn.execute("""
                    UPDATE evaluation_sessions 
                    SET status = $1, completed_at = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $3
                """, status, completed_at, session_id)
            else:
                result = await conn.execute("""
                    UPDATE evaluation_sessions 
                    SET status = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                """, status, session_id)
            
            return result.split()[1] == '1'  # Returns True if one row was updated
    
    async def update_session_counters(self, session_id: UUID, total: int, 
                                     successful: int, failed: int) -> bool:
        """Atualiza os contadores de uma sessão."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE evaluation_sessions 
                SET total_evaluations = $1, successful_evaluations = $2, 
                    failed_evaluations = $3, updated_at = CURRENT_TIMESTAMP
                WHERE id = $4
            """, total, successful, failed, session_id)
            
            return result.split()[1] == '1'
    
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[EvaluationSession]:
        """Lista sessões de avaliação."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM evaluation_sessions 
                ORDER BY created_at DESC 
                LIMIT $1 OFFSET $2
            """, limit, offset)
            
            return [EvaluationSession(**dict(row)) for row in rows]
    
    # Métodos para RagasEvaluation
    
    async def create_evaluation(self, evaluation: RagasEvaluation) -> UUID:
        """Cria uma nova avaliação RAGAS."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO ragas_evaluations (
                    session_id, email_id, user_context, search_query, 
                    generation_context, difficulty, hyde_context, 
                    fused_context, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, evaluation.session_id, evaluation.email_id, evaluation.user_context,
                evaluation.search_query, evaluation.generation_context, 
                evaluation.difficulty, evaluation.hyde_context, 
                evaluation.fused_context, evaluation.status)
            
            return row['id']
    
    async def get_evaluation_by_id(self, evaluation_id: UUID) -> Optional[RagasEvaluation]:
        """Busca uma avaliação por ID."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM ragas_evaluations WHERE id = $1
            """, evaluation_id)
            
            if row:
                return RagasEvaluation(**dict(row))
            return None
    
    async def update_evaluation_translations(self, evaluation_id: UUID, 
                                           expanded_pt: str, full_pt: str,
                                           expanded_en: str, full_en: str) -> bool:
        """Atualiza as traduções de uma avaliação."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE ragas_evaluations 
                SET expanded_answer_pt = $1, full_answer_pt = $2,
                    expanded_answer_en = $3, full_answer_en = $4,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $5
            """, expanded_pt, full_pt, expanded_en, full_en, evaluation_id)
            
            return result.split()[1] == '1'
    
    async def update_evaluation_status(self, evaluation_id: UUID, status: str, 
                                     error_message: Optional[str] = None) -> bool:
        """Atualiza o status de uma avaliação."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE ragas_evaluations 
                SET status = $1, error_message = $2, updated_at = CURRENT_TIMESTAMP
                WHERE id = $3
            """, status, error_message, evaluation_id)
            
            return result.split()[1] == '1'
    
    async def list_evaluations_by_session(self, session_id: UUID) -> List[RagasEvaluation]:
        """Lista avaliações de uma sessão."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM ragas_evaluations 
                WHERE session_id = $1 
                ORDER BY created_at
            """, session_id)
            
            return [RagasEvaluation(**dict(row)) for row in rows]
    
    async def list_evaluations_by_email(self, email_id: UUID) -> List[RagasEvaluation]:
        """Lista avaliações de um email específico."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM ragas_evaluations 
                WHERE email_id = $1 
                ORDER BY created_at DESC
            """, email_id)
            
            return [RagasEvaluation(**dict(row)) for row in rows]
    
    # Métodos para EvaluationRetrievedDocument
    
    async def create_retrieved_document(self, document: EvaluationRetrievedDocument) -> UUID:
        """Salva um documento recuperado."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO evaluation_retrieved_documents (
                    evaluation_id, document_order, document_id, document_text,
                    parent_content, similarity_score, rerank_score, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
            """, document.evaluation_id, document.document_order, document.document_id,
                document.document_text, document.parent_content, document.similarity_score,
                document.rerank_score, document.metadata)
            
            return row['id']
    
    async def get_retrieved_documents(self, evaluation_id: UUID) -> List[EvaluationRetrievedDocument]:
        """Busca documentos recuperados de uma avaliação."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM evaluation_retrieved_documents 
                WHERE evaluation_id = $1 
                ORDER BY document_order
            """, evaluation_id)
            
            return [EvaluationRetrievedDocument(**dict(row)) for row in rows]
    
    # Métodos para RagasMetric
    
    async def create_metric(self, metric: RagasMetric) -> UUID:
        """Salva uma métrica RAGAS."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO ragas_metrics (
                    evaluation_id, metric_name, metric_value, 
                    metric_category, metadata
                ) VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, metric.evaluation_id, metric.metric_name, metric.metric_value,
                metric.metric_category, metric.metadata)
            
            return row['id']
    
    async def create_metrics_batch(self, metrics: List[RagasMetric]) -> List[UUID]:
        """Salva múltiplas métricas em lote."""
        if not metrics:
            return []
        
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                ids = []
                for metric in metrics:
                    row = await conn.fetchrow("""
                        INSERT INTO ragas_metrics (
                            evaluation_id, metric_name, metric_value, 
                            metric_category, metadata
                        ) VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """, metric.evaluation_id, metric.metric_name, metric.metric_value,
                        metric.metric_category, metric.metadata)
                    ids.append(row['id'])
                
                return ids
    
    async def get_metrics_by_evaluation(self, evaluation_id: UUID) -> List[RagasMetric]:
        """Busca métricas de uma avaliação."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM ragas_metrics 
                WHERE evaluation_id = $1 
                ORDER BY metric_name
            """, evaluation_id)
            
            return [RagasMetric(**dict(row)) for row in rows]
    
    async def get_metrics_by_session(self, session_id: UUID) -> List[RagasMetric]:
        """Busca todas as métricas de uma sessão."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT rm.* FROM ragas_metrics rm
                JOIN ragas_evaluations re ON rm.evaluation_id = re.id
                WHERE re.session_id = $1
                ORDER BY re.created_at, rm.metric_name
            """, session_id)
            
            return [RagasMetric(**dict(row)) for row in rows]
    
    # Métodos para EvaluationSessionResult
    
    async def create_session_result(self, result: EvaluationSessionResult) -> UUID:
        """Salva resultado agregado de sessão."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO evaluation_session_results (
                    session_id, metric_name, avg_value, min_value, max_value,
                    std_deviation, median_value, total_samples
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (session_id, metric_name)
                DO UPDATE SET 
                    avg_value = EXCLUDED.avg_value,
                    min_value = EXCLUDED.min_value,
                    max_value = EXCLUDED.max_value,
                    std_deviation = EXCLUDED.std_deviation,
                    median_value = EXCLUDED.median_value,
                    total_samples = EXCLUDED.total_samples,
                    created_at = CURRENT_TIMESTAMP
                RETURNING id
            """, result.session_id, result.metric_name, result.avg_value,
                result.min_value, result.max_value, result.std_deviation,
                result.median_value, result.total_samples)
            
            return row['id']
    
    async def get_session_results(self, session_id: UUID) -> List[EvaluationSessionResult]:
        """Busca resultados agregados de uma sessão."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM evaluation_session_results 
                WHERE session_id = $1 
                ORDER BY metric_name
            """, session_id)
            
            return [EvaluationSessionResult(**dict(row)) for row in rows]
    
    # Métodos para Views
    
    async def get_evaluation_metrics_summary(self, 
                                           session_id: Optional[UUID] = None,
                                           email_id: Optional[UUID] = None,
                                           limit: int = 100) -> List[EvaluationMetricsSummary]:
        """Busca resumo de métricas usando a view."""
        async with self.db_pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch("""
                    SELECT ems.* FROM evaluation_metrics_summary ems
                    JOIN ragas_evaluations re ON ems.evaluation_id = re.id
                    WHERE re.session_id = $1
                    ORDER BY ems.created_at DESC
                    LIMIT $2
                """, session_id, limit)
            elif email_id:
                rows = await conn.fetch("""
                    SELECT * FROM evaluation_metrics_summary 
                    WHERE email_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """, email_id, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM evaluation_metrics_summary 
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)
            
            return [EvaluationMetricsSummary(**dict(row)) for row in rows]
    
    async def get_session_performance_overview(self, 
                                             session_id: Optional[UUID] = None) -> List[SessionPerformanceOverview]:
        """Busca overview de performance usando a view."""
        async with self.db_pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch("""
                    SELECT * FROM session_performance_overview 
                    WHERE session_id = $1
                """, session_id)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM session_performance_overview 
                    ORDER BY started_at DESC
                """)
            
            return [SessionPerformanceOverview(**dict(row)) for row in rows]
    
    # Métodos utilitários
    
    async def get_pending_evaluations(self, limit: int = 10) -> List[RagasEvaluation]:
        """Busca avaliações pendentes para processamento."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM ragas_evaluations 
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT $1
            """, limit)
            
            return [RagasEvaluation(**dict(row)) for row in rows]
    
    async def count_evaluations_by_status(self, session_id: Optional[UUID] = None) -> Dict[str, int]:
        """Conta avaliações por status."""
        async with self.db_pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch("""
                    SELECT status, COUNT(*) as count 
                    FROM ragas_evaluations 
                    WHERE session_id = $1
                    GROUP BY status
                """, session_id)
            else:
                rows = await conn.fetch("""
                    SELECT status, COUNT(*) as count 
                    FROM ragas_evaluations 
                    GROUP BY status
                """)
            
            return {row['status']: row['count'] for row in rows}
    
    async def delete_session_cascade(self, session_id: UUID) -> bool:
        """Remove uma sessão e todos os dados relacionados."""
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                # A configuração CASCADE do banco já cuida da remoção em cascata
                result = await conn.execute("""
                    DELETE FROM evaluation_sessions WHERE id = $1
                """, session_id)
                
                return result.split()[1] == '1'