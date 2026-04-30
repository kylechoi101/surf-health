# Backend Cleanup & Security Audit Design

**Date:** 2026-04-30
**Scope:** Surgical backend cleanup of NVIDIA/Ollama logic + Standard project-wide security audit.

## 1. Backend Cleanup (Surgical)
The objective is to remove experimental LLM components while preserving the traditional ML pipeline (e.g. `training.py`, `calibration.py`).

**Target Removals:**
- `backend/app/ml/feature_agent/run_agent.py`
- `backend/app/services/ollama_service.py`
- `scripts/nim_worker.py`
- `scripts/run_nim_workers.sh`

**Target Modifications:**
- `backend/.env.example`: Remove `OLLAMA_*` and `NVIDIA_*` keys.
- `.gitignore`: Remove entries like `nvidia_status.txt`, `nim_worker.log`, `nim_worker.pid`.
- `README.md`: Strip out references to Ollama.
- `backend/app/ml/feature_agent/agent_features.py` (and similar files): Ensure they have no dangling imports or calls to deleted files.

## 2. Security Audit (Standard)
A systematic review to secure the application before EAS/TestFlight deployment.

**Audit Areas:**
- **Secret Scanning:** Use global search for exposed credentials, `.env` files, `.pem` keys, and sensitive tokens (AWS, NVIDIA, OpenAI, API_KEY).
- **Git Tracking:** Verify that `.gitignore` correctly ignores all sensitive files (like `.env`, `__pycache__`, and keys).
- **Dependency Vulnerabilities:** Execute security audits on `web` and `mobile` using `npm audit`, and check the backend dependencies using `pip-audit` or `safety` (if available).
- **API & Network Configuration:** Review `backend/app/main.py` for CORS misconfigurations and unauthenticated sensitive routes. Check `render.yaml` for correct environment variable settings (`APP_ENV=production`).

## 3. Deployment
Once the cleanup and audit are resolved, the subsequent tasks will focus on the mobile deployment (EAS build and TestFlight). This is covered under a separate sub-project plan.