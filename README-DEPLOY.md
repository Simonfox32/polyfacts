# Polyfacts Deployment Guide

## Local Development (Docker Compose)

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f backend

# Stop
docker compose down
```

## Deploy to Railway

### Backend
1. Create new project on [railway.app](https://railway.app)
2. Add PostgreSQL service (with pgvector)
3. Add Redis service
4. Connect your GitHub repo, set root directory to `backend/`
5. Set environment variables (copy from `.env.example`)
6. Railway auto-deploys on push

### Frontend (Vercel)
1. Import repo on [vercel.com](https://vercel.com)
2. Set root directory to `frontend/`
3. Add env var: `NEXT_PUBLIC_API_URL=https://your-backend.railway.app`
4. Deploy

### Frontend (Railway alternative)
1. Add another service in Railway
2. Set root directory to `frontend/`
3. Set build arg: `NEXT_PUBLIC_API_URL=https://your-backend.railway.app`

## Environment Variables

See `backend/.env.example` for required API keys.

Required for core functionality:
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- `DEEPGRAM_API_KEY` — Audio transcription
- `GROQ_API_KEY` — LLM for claim detection, speaker ID, verdicts
- `BRAVE_SEARCH_API_KEY` — Web evidence search
- `JWT_SECRET` — Set a strong random string in production

Optional:
- `ANTHROPIC_API_KEY` — Face identification from video
- `OPENAI_API_KEY` — Embeddings
- `CORS_ORIGINS` — Comma-separated allowed origins (default: *)
