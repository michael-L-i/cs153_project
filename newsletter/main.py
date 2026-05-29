from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsletter.auth import AuthUser, get_current_user
from newsletter.config import get_settings
from newsletter.db import create_db_and_tables, get_db_session
from newsletter.models import Dossier, Event, ResearchJob, Source, Subject
from newsletter.services import chat as chat_service
from newsletter.services import newsletter as newsletter_service
from newsletter.schemas import (
    DossierRead,
    EventRead,
    ResearchJobCreate,
    ResearchJobRead,
    SourceRead,
    SubjectCreate,
    SubjectRead,
    WriterInputCreate,
    WriterPacket,
)
from newsletter.services.ingestion import ingest_document
from newsletter.services.research import ResearchService
from newsletter.services.vector import search as vector_search
from newsletter.services.writer import build_writer_packet

research_service = ResearchService()


class ChatRequest(BaseModel):
    message: str


class CreateConversationRequest(BaseModel):
    title: str | None = None


class RenameConversationRequest(BaseModel):
    title: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Founder Newsletter Research Platform", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/auth/config")
    def auth_config() -> dict[str, str | None]:
        s = get_settings()
        return {"supabase_url": s.supabase_url, "supabase_anon_key": s.supabase_anon_key}

    @app.get("/founders")
    def list_founders(session: Session = Depends(get_db_session)) -> dict:
        rows = session.execute(
            select(
                Subject,
                func.count(Source.id).label("source_count"),
            )
            .outerjoin(Source, Source.subject_id == Subject.id)
            .group_by(Subject.id)
            .order_by(Subject.created_at.desc())
        ).all()

        founders = []
        for subject, source_count in rows:
            founders.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "company_name": subject.company_name,
                    "notes": subject.notes,
                    "source_count": int(source_count or 0),
                    "created_at": subject.created_at.isoformat(),
                }
            )
        return {"count": len(founders), "founders": founders}

    @app.get("/founders/{subject_id}")
    def get_founder(subject_id: str, session: Session = Depends(get_db_session)) -> dict:
        row = session.execute(
            select(Subject, func.count(Source.id).label("source_count"))
            .outerjoin(Source, Source.subject_id == Subject.id)
            .where(Subject.id == subject_id)
            .group_by(Subject.id)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Founder not found.")
        subject, source_count = row
        return {
            "id": subject.id,
            "name": subject.name,
            "company_name": subject.company_name,
            "notes": subject.notes,
            "source_count": int(source_count or 0),
            "created_at": subject.created_at.isoformat(),
        }

    def _serialize_conversation(c) -> dict:
        return {
            "id": c.id,
            "subject_id": c.subject_id,
            "title": c.title or "New conversation",
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }

    @app.get("/founders/{subject_id}/conversations")
    def list_conversations(
        subject_id: str,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        if session.get(Subject, subject_id) is None:
            raise HTTPException(status_code=404, detail="Founder not found.")
        rows = chat_service.list_conversations(session, subject_id, user_id=user.id)
        return {"conversations": [_serialize_conversation(c) for c in rows]}

    @app.post("/founders/{subject_id}/conversations")
    def create_conversation(
        subject_id: str,
        payload: CreateConversationRequest,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        try:
            convo = chat_service.create_conversation(session, subject_id, user_id=user.id, title=payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _serialize_conversation(convo)

    @app.get("/founders/{subject_id}/conversations/{conversation_id}/messages")
    def get_conversation_messages(
        subject_id: str,
        conversation_id: str,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        try:
            rows = chat_service.list_messages(session, conversation_id, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "messages": [
                {"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
                for r in rows
            ]
        }

    @app.post("/founders/{subject_id}/conversations/{conversation_id}/chat")
    def post_conversation_chat(
        subject_id: str,
        conversation_id: str,
        payload: ChatRequest,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        message = (payload.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message is empty.")
        try:
            reply = chat_service.respond(session, conversation_id, message, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"reply": reply}

    @app.patch("/founders/{subject_id}/conversations/{conversation_id}")
    def rename_conversation(
        subject_id: str,
        conversation_id: str,
        payload: RenameConversationRequest,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        try:
            convo = chat_service.rename_conversation(session, conversation_id, user_id=user.id, title=payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _serialize_conversation(convo)

    @app.delete("/founders/{subject_id}/conversations/{conversation_id}")
    def delete_conversation(
        subject_id: str,
        conversation_id: str,
        session: Session = Depends(get_db_session),
        user: AuthUser = Depends(get_current_user),
    ) -> dict:
        try:
            chat_service.delete_conversation(session, conversation_id, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"deleted": conversation_id}

    @app.post("/founders/{subject_id}/newsletter")
    def post_founder_newsletter(
        subject_id: str,
        session: Session = Depends(get_db_session),
    ) -> dict:
        if session.get(Subject, subject_id) is None:
            raise HTTPException(status_code=404, detail="Founder not found.")
        try:
            markdown = newsletter_service.write_newsletter(session, subject_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"markdown": markdown}

    @app.post("/subjects", response_model=SubjectRead)
    def create_subject(payload: SubjectCreate, session: Session = Depends(get_db_session)) -> Subject:
        subject = Subject(**payload.model_dump())
        session.add(subject)
        session.commit()
        session.refresh(subject)
        return subject

    @app.post("/research-jobs", response_model=ResearchJobRead)
    def create_research_job(
        payload: ResearchJobCreate,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_db_session),
    ) -> ResearchJob:
        subject = session.get(Subject, payload.subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found.")

        job = ResearchJob(subject_id=payload.subject_id)
        session.add(job)
        session.commit()
        session.refresh(job)

        mode = payload.mode or get_settings().default_research_job_mode
        if mode == "inline":
            research_service.run_job(job.id)
            session.refresh(job)
        else:
            background_tasks.add_task(research_service.run_job, job.id)
        return job

    @app.get("/research-jobs/{job_id}", response_model=ResearchJobRead)
    def get_research_job(job_id: str, session: Session = Depends(get_db_session)) -> ResearchJob:
        job = session.get(ResearchJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Research job not found.")
        return job

    @app.get("/subjects/{subject_id}/sources", response_model=list[SourceRead])
    def get_subject_sources(subject_id: str, session: Session = Depends(get_db_session)) -> list[Source]:
        subject = session.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found.")
        return session.scalars(select(Source).where(Source.subject_id == subject_id).order_by(Source.created_at)).all()

    @app.get("/subjects/{subject_id}/timeline", response_model=list[EventRead])
    def get_subject_timeline(subject_id: str, session: Session = Depends(get_db_session)) -> list[Event]:
        subject = session.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found.")
        return session.scalars(
            select(Event).where(Event.subject_id == subject_id).order_by(Event.event_date, Event.created_at)
        ).all()

    @app.get("/subjects/{subject_id}/dossier", response_model=DossierRead)
    def get_subject_dossier(subject_id: str, session: Session = Depends(get_db_session)) -> Dossier:
        subject = session.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found.")
        dossier = session.scalars(
            select(Dossier).where(Dossier.subject_id == subject_id).order_by(Dossier.version.desc())
        ).first()
        if dossier is None:
            raise HTTPException(status_code=404, detail="No dossier available for subject.")
        return dossier

    @app.post("/documents/{document_id}/ingest")
    def trigger_ingest(document_id: str, session: Session = Depends(get_db_session)) -> dict:
        """Chunk a document and upsert its vectors into Qdrant."""
        from newsletter.models import Document
        doc = session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        count = ingest_document(document_id, session)
        return {"document_id": document_id, "chunks_upserted": count}

    @app.get("/search")
    def semantic_search(
        q: str,
        subject_id: str | None = None,
        source_type: str | None = None,
        limit: int = 8,
    ) -> dict:
        """Semantic search over the founders corpus. Optionally filter by subject_id."""
        results = vector_search(q, subject_id=subject_id, source_type=source_type, limit=limit)
        return {
            "query": q,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "score": r.score,
                    "text": r.text,
                    "subject_id": r.subject_id,
                    "source_type": r.source_type,
                    "source_url": r.source_url,
                }
                for r in results
            ],
        }

    @app.post("/writer-inputs", response_model=WriterPacket)
    def create_writer_inputs(payload: WriterInputCreate, session: Session = Depends(get_db_session)) -> WriterPacket:
        subject = session.get(Subject, payload.subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found.")
        dossier = session.scalars(
            select(Dossier).where(Dossier.subject_id == payload.subject_id).order_by(Dossier.version.desc())
        ).first()
        if dossier is None:
            raise HTTPException(status_code=404, detail="No dossier available for subject.")
        return build_writer_packet(
            subject=subject,
            dossier=dossier,
            max_claims=payload.max_claims,
            max_quotes=payload.max_quotes,
            max_events=payload.max_events,
        )

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app


app = create_app()

