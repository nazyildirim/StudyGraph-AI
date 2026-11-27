"""Application service orchestrating grounded RAG question answering (Issue #8).

Workflow (K46):
1. Validate user, question, and answer mode.
2. Verify `CourseAccessPolicy` (unauthorized users never trigger retrieval or LLM).
3. Retrieve course-scoped chunks via `CourseRetrievalService`.
4. If `NO_SOURCES`, skip LLM completely, persist `RagQuery(grounded=False)`,
   and return an explicit no-sources response with zero citations.
5. Build prompt (`PromptBuilder`) outside any DB transaction/lock.
6. Generate answer (`LLMClient`) and validate citations (`CitationValidator`),
   with at most 1 controlled retry on invalid JSON or invalid citations.
7. Fall back to `ExtractiveLLMClient` ONLY on explicit LLM unavailability or
   repeated invalid output (never on access denial or DB errors), clearly
   marking `fallback_used=True`.
8. Re-verify `CourseAccessPolicy` before persistence, then atomically persist
   `RagQuery` + `RagQueryCitation` (which also enforces same-course chunk FK
   integrity in one transaction).
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from app.authorization.course_access_policy import CourseAccessPolicy
from app.models.user import User
from app.rag.domain.types import CitationDraft, RetrievalStatus
from app.rag.generation.citation_validator import CitationValidator
from app.rag.generation.errors import (
    CitationValidationError,
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)
from app.rag.generation.extractive_client import ExtractiveLLMClient
from app.rag.generation.prompt_builder import PromptBuilder
from app.rag.generation.protocol import LLMClient
from app.rag.generation.types import (
    AnswerMode,
    AssistantAnswer,
    LLMRequest,
    LLMResponse,
    ValidatedSource,
)
from app.rag.retrieval.retrieval_service import CourseRetrievalService
from app.repositories.rag_query_repository import RagQueryRepository

NO_SOURCES_ANSWER_TR = (
    "Yüklenen ders materyallerinde bu soruyla ilgili yeterli kaynak bulunamadı. "
    "Soruyu ders konularıyla ilişkilendirerek veya daha açık biçimde tekrar "
    "sorabilirsiniz."
)


class RagAssistantService:
    """Orchestrates authorized retrieval, LLM generation, citation validation, and logging."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        retrieval_service: CourseRetrievalService,
        prompt_builder: PromptBuilder,
        llm_client: LLMClient,
        citation_validator: CitationValidator,
        query_repository: RagQueryRepository,
        extractive_fallback: ExtractiveLLMClient | None = None,
        max_output_tokens: int = 512,
        temperature: float = 0.2,
        context_window: int = 4096,
        release_db_connection: Callable[[], None] | None = None,
    ) -> None:
        self._access = access_policy
        self._retrieval = retrieval_service
        self._prompts = prompt_builder
        self._llm = llm_client
        self._validator = citation_validator
        self._queries = query_repository
        self._fallback = extractive_fallback
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._context_window = context_window
        self._release_db = release_db_connection

    def ask(
        self,
        *,
        user: User,
        course_id: int,
        question: str,
        mode: AnswerMode = AnswerMode.EXPLAIN,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> AssistantAnswer:
        mode = AnswerMode(mode)
        # Snapshot scalar identity fields so releasing the SQLAlchemy session
        # before the LLM call can never trigger DetachedInstanceError.
        user_snapshot: User = SimpleNamespace(
            id=user.id,
            role=user.role,
            is_active=user.is_active,
        )  # type: ignore[assignment]

        # 1-3. Access check + retrieval (never invokes LLM if unauthorized).
        retrieval = self._retrieval.retrieve(
            user=user_snapshot,
            course_id=course_id,
            query=question,
            top_k=top_k,
            min_score=min_score,
        )

        # 4. Empty retrieval -> NEVER call LLM; persist grounded=False.
        if retrieval.status is RetrievalStatus.NO_SOURCES or not retrieval.chunks:
            self._access.check_read_access(user_snapshot, course_id)
            stored = self._queries.create_with_citations(
                student_id=user_snapshot.id,
                course_id=course_id,
                question=question.strip(),
                answer=NO_SOURCES_ANSWER_TR,
                grounded=False,
                model_name=None,
                citations=[],
            )
            return AssistantAnswer(
                query_id=stored.id,
                answer=NO_SOURCES_ANSWER_TR,
                grounded=False,
                mode=mode,
                sources=(),
                model_name=None,
                retrieval_method=retrieval.method.value,
                fallback_used=retrieval.fallback_used,
                fallback_reason=retrieval.fallback_reason,
            )

        # Release pooled DB connection BEFORE slow Ollama LLM generation (HIGH-2).
        if self._release_db is not None:
            self._release_db()

        # 5-7. Build prompt, call LLM (zero DB connection held), validate citations.
        llm_response, grounded, validated_sources, fallback_used, fallback_reason = (
            self._generate_and_validate(
                question=question,
                chunks=retrieval.chunks,
                course_id=course_id,
                mode=mode,
            )
        )

        # 8. Re-verify access right before persisting (guards against mid-flight revocation).
        self._access.check_read_access(user_snapshot, course_id)

        # 9. Atomic persistence of RagQuery + verified RagQueryCitation rows.
        citation_drafts = [
            CitationDraft(
                chunk_id=src.chunk_id,
                relevance_score=_clamp_score_for_db(src.relevance_score),
            )
            for src in validated_sources
        ]
        stored = self._queries.create_with_citations(
            student_id=user_snapshot.id,
            course_id=course_id,
            question=question.strip(),
            answer=llm_response.answer,
            grounded=grounded,
            model_name=llm_response.model_name,
            citations=citation_drafts if grounded else [],
        )

        effective_fallback = fallback_used or retrieval.fallback_used
        effective_reason = fallback_reason or retrieval.fallback_reason
        return AssistantAnswer(
            query_id=stored.id,
            answer=llm_response.answer,
            grounded=grounded,
            mode=mode,
            sources=validated_sources if grounded else (),
            model_name=llm_response.model_name,
            retrieval_method=retrieval.method.value,
            fallback_used=effective_fallback,
            fallback_reason=effective_reason,
        )

    def _generate_and_validate(
        self,
        *,
        question: str,
        chunks,
        course_id: int,
        mode: AnswerMode,
    ) -> tuple[LLMResponse, bool, tuple[ValidatedSource, ...], bool, str | None]:
        retry_hint: str | None = None
        last_error: Exception | None = None

        # At most 1 controlled retry on invalid JSON or invalid citations.
        for attempt in range(2):
            built = self._prompts.build(
                question=question,
                chunks=chunks,
                mode=mode,
                retry_hint=retry_hint,
            )
            request = LLMRequest(
                system_prompt=built.system_prompt,
                user_prompt=built.user_prompt,
                response_schema=built.response_schema,
                sources=built.sources,
                mode=mode,
                max_output_tokens=self._max_output_tokens,
                temperature=self._temperature,
                context_window=self._context_window,
            )
            try:
                response = self._llm.generate(request)
                grounded, validated = self._validator.validate(
                    response=response,
                    sources=built.sources,
                    expected_course_id=course_id,
                )
                return response, grounded, validated, response.is_fallback, (
                    "extractive_mode" if response.is_fallback else None
                )
            except (LLMConnectionError, LLMTimeoutError) as error:
                if self._fallback is None:
                    raise
                fb_resp = self._fallback.generate(request)
                grounded, validated = self._validator.validate(
                    response=fb_resp,
                    sources=built.sources,
                    expected_course_id=course_id,
                )
                return (
                    fb_resp,
                    grounded,
                    validated,
                    True,
                    f"llm_unavailable:{type(error).__name__}",
                )
            except (LLMInvalidResponseError, CitationValidationError) as error:
                last_error = error
                if attempt == 0:
                    allowed = [s.source_id for s in built.sources]
                    retry_hint = (
                        f"Your previous output failed validation ({type(error).__name__}). "
                        f"Return valid JSON and cite ONLY IDs from {allowed}."
                    )
                    continue

        if self._fallback is not None:
            built = self._prompts.build(question=question, chunks=chunks, mode=mode)
            request = LLMRequest(
                system_prompt=built.system_prompt,
                user_prompt=built.user_prompt,
                response_schema=built.response_schema,
                sources=built.sources,
                mode=mode,
            )
            fb_resp = self._fallback.generate(request)
            grounded, validated = self._validator.validate(
                response=fb_resp,
                sources=built.sources,
                expected_course_id=course_id,
            )
            return (
                fb_resp,
                grounded,
                validated,
                True,
                f"llm_validation_failed:{type(last_error).__name__}",
            )

        assert last_error is not None
        raise last_error


def _clamp_score_for_db(score: float) -> float | None:
    """rag_query_citations.relevance_score is constrained to [0.0, 1.0]."""
    if 0.0 <= score <= 1.0:
        return score
    # BM25 scores can exceed 1.0; store None rather than distorting the scale.
    return None
