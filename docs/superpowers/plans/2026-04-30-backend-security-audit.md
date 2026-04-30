# Backend Cleanup and Security Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up experimental LLM tools and audit security posture.

**Architecture:** Surgically remove `run_agent.py`, `ollama_service.py`, and `nim_worker` scripts, then perform a systematic secret and dependency scan.

**Tech Stack:** Bash, Python, Node.

---

### Task 1: Delete experimental files

**Files:**
- Delete: `backend/app/ml/feature_agent/run_agent.py`
- Delete: `backend/app/services/ollama_service.py`
- Delete: `scripts/nim_worker.py`
- Delete: `scripts/run_nim_workers.sh`

- [ ] **Step 1: Delete the files**
```bash
git rm backend/app/ml/feature_agent/run_agent.py backend/app/services/ollama_service.py scripts/nim_worker.py scripts/run_nim_workers.sh
```

- [ ] **Step 2: Commit**
```bash
git commit -m "chore: remove experimental LLM agents and worker scripts"
```

### Task 2: Clean environment and ignore configs

**Files:**
- Modify: `backend/.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Clean backend/.env.example**
Open `backend/.env.example` and remove lines containing `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `NVIDIA_API_KEY` (if present).

- [ ] **Step 2: Clean .gitignore**
Open `.gitignore` and remove lines containing `nvidia_status.txt`, `nim_worker.log`, and `nim_worker.pid`.

- [ ] **Step 3: Commit**
```bash
git add backend/.env.example .gitignore
git commit -m "chore: remove LLM entries from env and gitignore"
```

### Task 3: Clean Documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `backend/app/ml/feature_agent/agent_features.py`

- [ ] **Step 1: Clean README.md**
Open `README.md` and remove any bullets or mentions of Ollama/NIM.

- [ ] **Step 2: Clean CLAUDE.md**
Open `CLAUDE.md` and remove the line referencing `run_agent.py`.

- [ ] **Step 3: Clean agent_features.py**
Open `backend/app/ml/feature_agent/agent_features.py` and modify the top comment mentioning `run_agent.py`.

- [ ] **Step 4: Commit**
```bash
git add README.md CLAUDE.md backend/app/ml/feature_agent/agent_features.py
git commit -m "docs: remove LLM agent references from docs"
```

### Task 4: Security Audit - Code Scan

**Files:** None directly created/modified initially.

- [ ] **Step 1: Search for hardcoded secrets**
```bash
grep -rn "API_KEY" . || echo "No API_KEY found"
grep -rn "SECRET" . || echo "No SECRET found"
```
(Manually inspect findings. If any true secrets are found in tracked files, they must be removed in this step.)

- [ ] **Step 2: Check for unignored .env files**
```bash
git ls-files | grep "\.env" || echo "No tracked .env files"
```

- [ ] **Step 3: Check API configuration**
Open `backend/app/main.py` to ensure CORS and any auth configurations are secure. Review `render.yaml` to ensure production environment is set.

- [ ] **Step 4: Resolve & Commit (If applicable)**
If issues found, fix them and commit.

### Task 5: Security Audit - Dependencies

**Files:** None directly created/modified initially.

- [ ] **Step 1: Audit Node dependencies**
```bash
cd web && npm audit
cd ../mobile && npm audit
```
(Update critical severity issues if easily resolvable.)

- [ ] **Step 2: Audit Python dependencies**
```bash
cd backend && (pip-audit || echo "pip-audit not available, manually check requirements")
```

- [ ] **Step 3: Commit any lockfile changes**
If `npm audit fix` or similar was run, commit the changes.
```bash
git add web/package-lock.json mobile/package-lock.json
git commit -m "chore: security audit dependency updates"
```