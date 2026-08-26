# Virtual Judge — Project Status

## Overview

AI-powered judging for hackathons and pitch events. Records pitches, transcribes with audio-capable models, scores against rubrics with Claude, and plays back reviews with natural speech synthesis.

## Repo Baseline Score

| Component | Score | Last Audited | Status |
|-----------|-------|--------------|--------|
| Repo Baseline | 95% (24/25) | 2026-08-25 | ✅ Build Ready |

## Audit Compliance (2026-08-25)

**Before fixes:** 72% (18/25)  
**After fixes:** 95% (24/25)

### Fixed
- ✅ Created `.gates.yaml` with repo_baseline and build_ready gates
- ✅ Added `/api/version` endpoint for deployment traceability
- ✅ Created `.editorconfig` for cross-editor consistency
- ✅ Pinned edge-tts to exact version
- ✅ Injected build metadata into CI

### Remaining (Scale phase only)
- ⚠️ No OSV Scanner in CI — add for production
- ⚠️ No Harden-Runner in CI — add for production

### Critical (resolved)
- 🔴 ~~`.env` tracked in git with live keys~~ → Keys rotated 2026-08-25

## Tech Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn |
| Frontend | Vanilla JS + HTML in static directory |
| Database | SQLite (local file) |
| LLM | OpenRouter (Claude Sonnet 5 scoring, Gemini 3.7 Flash transcription) |
| Voice | ElevenLabs |
| E2E tests | Playwright + Chromium |
| Linting | ruff (Python) + ESLint (JavaScript) |
| Tests | pytest (378 tests) + Playwright |
| CI | GitHub Actions |

## Key Features

1. **Record** — Team records pitch via browser
2. **Transcribe** — Audio converted to text (Gemini)
3. **Score** — LLM evaluates against rubric (Claude Sonnet 5)
4. **Speak** — Review played back in natural voice (ElevenLabs)
5. **Finalist** — Compare all teams, rank top 3
6. **PRFAQ** — Generate Working Backwards doc per team

## Known Issues

- 2 ESLint race condition warnings in `static/index.html` (lines 863, 1644)
  - Low severity (UI state synchronization), prioritize for Polish phase

## Deployment

- **Dev:** `npm run dev` — hot reload, localhost:8000
- **Production:** `npm run start` — network-bound, requires `VJ_ACCESS_CODE`
- **Environment variables:** OPENROUTER_API_KEY, ELEVENLABS_API_KEY (rotated 2026-08-25)
- **Version endpoint:** GET `/api/version` — returns build number, commit, deploy date

## Next Steps

1. Address ESLint race condition warnings (Polish phase)
2. Add OSV Scanner to CI (Production phase)
3. Add Harden-Runner action to CI (Production phase)
4. Create deployment guide (if hosting externally)
