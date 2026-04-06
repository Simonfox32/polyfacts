# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polyfacts is a political fact-checking platform that automates: audio transcription → claim detection → evidence retrieval → citation-backed verdict generation. Verdicts are one of: TRUE, MOSTLY_TRUE, HALF_TRUE, MOSTLY_FALSE, FALSE, UNVERIFIED.

## Commands

### Backend (Python 3.12+, from `backend/`)

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dev server
uvicorn app.main:app --reload --port 8000

# Background worker (requires Redis)
arq app.worker.WorkerSettings

# Database migrations
alembic upgrade head

# Seed demo data
python -m scripts.seed_demo

# Tests
pytest                              # all tests
pytest tests/test_claim_detector.py # single file

# Linting & type checking
ruff check .
mypy .
```

### Frontend (Node 18+, from `frontend/`)

```bash
npm install
npm run dev       # dev server at localhost:3000
npm run build     # production build
npm run lint      # ESLint
```

## Architecture

### Pipeline Stages (backend/app/services/)

The system processes clips through a sequential pipeline orchestrated by `pipeline.py`:

1. **ASR** (`asr_pipeline.py`) — Deepgram Nova-2 transcription with speaker diarization
2. **Speaker ID** (`pipeline.py._identify_speakers()`) — Claude identifies speakers from utterance context
3. **Claim Detection** (`claim_detector.py`) — Two-stage: heuristic worthiness scoring (0-1, threshold ≥0.3) then Claude Haiku extracts structured claim data
4. **Evidence Retrieval** (`evidence_retriever.py`) — Hybrid search combining BM25 + pgvector embeddings + government APIs + web search, merged via Reciprocal Rank Fusion (RRF)
5. **Verdict Generation** (`verdict_engine.py`) — Claude generates verdicts constrained to cite [SOURCE_N] references; cannot produce verdicts without evidence

### Backend Stack

- **FastAPI** with async throughout (asyncpg, httpx, arq)
- **PostgreSQL + pgvector** for relational data and 1536-dim embeddings
- **Redis + arq** for background job queue (upload returns 202, frontend polls status)
- **SQLAlchemy 2.0** async ORM with Alembic migrations
- Routes inject DB sessions via `Depends(get_db)`

### Frontend Stack

- **Next.js 14** (App Router) with React 18, TypeScript, Tailwind CSS
- API calls go to `/api/*` which Next.js rewrites to backend `http://localhost:8000/v1/*` (see `next.config.mjs`)
- Frontend polls `/api/clips/{id}/status` every 2-3 seconds during processing

### API Routes (backend/app/routes/)

- `POST /v1/clips` — Upload clip, returns 202
- `GET /v1/clips/{id}/status` — Poll processing progress
- `GET /v1/sessions` — List sessions
- `GET /v1/sessions/{id}/claims` — List claims (filterable by verdict, speaker)
- `GET /v1/sessions/{id}/transcript` — Get transcript segments
- `GET /v1/claims/{id}` — Claim detail with sources and evidence

### Data Model (backend/app/models/)

All models use prefixed IDs (sess_, clm_, src_, evd_, seg_, aud_) and a TimestampMixin (created_at, updated_at). Key tables: sessions, claims, sources, evidence_passages, transcript_segments, verdict_audit_log.

JSONB columns are used for flexible schema: `normalized_claim`, `time_scope`, `verdict_rationale_bullets`, `evidence_ids`.

### Source Tiering

Evidence sources are ranked: tier_1_government_primary > tier_2_court_academic > tier_3_major_outlet > tier_4_regional_specialty > tier_5_other.

## Configuration

Backend settings via Pydantic Settings in `backend/app/config.py`, loaded from `backend/.env`. Required API keys: DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY. See `.env.example`.

## Code Style

- Backend: ruff (line length 100, rules: E, F, I, N, W), mypy, Python 3.12 target
- Frontend: ESLint via Next.js defaults
- pytest with `asyncio_mode = "auto"`
