"""Backward-compatible facade for the unified RAG/AI service.

The active implementation lives only in ``rag_ai.rag_ai_service``.
Older imports of InterviewAIService/SOURCE_RULES therefore continue to work
without keeping a second, divergent RAG implementation in the project.
"""

from rag_ai.rag_ai_service import (  # noqa: F401
    RagInterviewAI,
    SOURCE_RULES,
    INTERVIEW_TYPES,
    QUESTION_TYPES,
    SCORING_VERSION,
)

# Legacy class name kept so existing imports do not break.
InterviewAIService = RagInterviewAI
