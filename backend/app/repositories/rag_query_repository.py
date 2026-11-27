"""RagQuery / RagQueryCitation persistence abstraction and implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course_material import CourseMaterial
from app.models.material_chunk import MaterialChunk
from app.models.rag_query import RagQuery
from app.models.rag_query_citation import RagQueryCitation
from app.rag.domain.types import CitationDraft
from app.repositories.errors import (
    InvalidCitationError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
)


class RagQueryRepository(Protocol):
    """Repository contract for RAG question/answer logs and citations."""

    def create_with_citations(
        self,
        *,
        student_id: int,
        course_id: int,
        question: str,
        answer: str,
        grounded: bool,
        model_name: str | None,
        citations: Sequence[CitationDraft],
    ) -> RagQuery: ...

    def get_by_id(self, query_id: int) -> RagQuery | None: ...

    def list_citations(self, query_id: int) -> list[RagQueryCitation]: ...

    def list_for_student(
        self,
        student_id: int,
        course_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RagQuery]: ...


class SqlAlchemyRagQueryRepository:
    """SQLAlchemy 2.0 implementation of RagQueryRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_with_citations(
        self,
        *,
        student_id: int,
        course_id: int,
        question: str,
        answer: str,
        grounded: bool,
        model_name: str | None,
        citations: Sequence[CitationDraft],
    ) -> RagQuery:
        """Persist a query and its citations in one transaction.

        Every cited chunk must belong to a material of `course_id`; otherwise
        `InvalidCitationError` is raised and nothing is written. A query that is
        not grounded cannot carry citations.
        """
        chunk_ids = [citation.chunk_id for citation in citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise InvalidCitationError("Duplicate chunk in citations.")
        if citations and not grounded:
            raise InvalidCitationError("Ungrounded answers cannot have citations.")

        if chunk_ids:
            valid_count = len(
                self._session.execute(
                    select(MaterialChunk.id)
                    .join(
                        CourseMaterial,
                        CourseMaterial.id == MaterialChunk.material_id,
                    )
                    .where(
                        CourseMaterial.course_id == course_id,
                        MaterialChunk.id.in_(chunk_ids),
                    )
                ).all()
            )
            if valid_count != len(chunk_ids):
                raise InvalidCitationError(
                    "Citation chunk does not belong to the query's course."
                )

        query = RagQuery(
            student_id=student_id,
            course_id=course_id,
            question=question,
            answer=answer,
            grounded=grounded,
            model_name=model_name,
        )
        self._session.add(query)
        try:
            self._session.flush()
            self._session.add_all(
                RagQueryCitation(
                    query_id=query.id,
                    chunk_id=citation.chunk_id,
                    relevance_score=citation.relevance_score,
                )
                for citation in citations
            )
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("student, course or chunk") from error
            raise
        return query

    def get_by_id(self, query_id: int) -> RagQuery | None:
        return self._session.get(RagQuery, query_id)

    def list_citations(self, query_id: int) -> list[RagQueryCitation]:
        return list(
            self._session.execute(
                select(RagQueryCitation)
                .where(RagQueryCitation.query_id == query_id)
                .order_by(RagQueryCitation.id)
            ).scalars()
        )

    def list_for_student(
        self,
        student_id: int,
        course_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RagQuery]:
        return list(
            self._session.execute(
                select(RagQuery)
                .where(
                    RagQuery.student_id == student_id,
                    RagQuery.course_id == course_id,
                )
                .order_by(RagQuery.created_at.desc(), RagQuery.id.desc())
                .limit(limit)
                .offset(offset)
            ).scalars()
        )
