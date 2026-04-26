from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsletter.config import get_settings
from newsletter.db import create_db_and_tables, get_db_session
from newsletter.models import Dossier, Event, ResearchJob, Source, Subject
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
from newsletter.services.research import ResearchService
from newsletter.services.writer import build_writer_packet

research_service = ResearchService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Founder Newsletter Research Platform", lifespan=lifespan)

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

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

    return app


app = create_app()

