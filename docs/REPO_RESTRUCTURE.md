# Repo restructure — open-core migration

Plan to split the current public-everything monorepo into an **open-core**
structure: the ML pipeline + research methodology stays public (credibility
play), the user-facing apps go private (competitive surface area).

## Target structure

```
kylechoi101/surf-health             ← public, Apache 2.0
├── LICENSE
├── README.md                        (focused on methodology + how to reproduce)
├── backend/
│   ├── app/data/pipeline/           ← ingestion pipeline (public)
│   ├── app/ml/                      ← model code (public)
│   ├── app/api/                     ← API (public — anyone can self-host their own version)
│   ├── app/services/                ← public except sensitive logic
│   ├── tests/                       ← public
│   └── pyproject.toml
├── scripts/                         ← reproducible research scripts
├── data/curated/                    ← schemas + small samples
│   ├── beaches.parquet              ← OK to keep (public BeachWatch data)
│   └── ⚠ REMOVE: serving.sqlite, production_model.json, system_health.json
└── docs/                            ← methodology, model card

kylechoi101/shorelife-web            ← NEW PRIVATE repo
└── (move web/ here)

kylechoi101/shorelife-mobile         ← NEW PRIVATE repo
└── (move mobile/ here)

<private-repo>        ← NEW PRIVATE repo
├── configs/
│   ├── advisory_url_mapping.json    ← hand-curated county URLs
│   ├── photo_curation.json          ← curated Wikimedia photos
│   └── tuning_hyperparameters.yml   ← any model knobs that took experimentation
└── data/
    ├── serving.sqlite               ← model artifact (was in public repo)
    └── production_model.json        ← model registry
```

## Why this works as open core

| Layer | Public? | Why |
|---|---|---|
| Ingestion code (BeachWatch, CDIP, etc.) | Yes | Commodity — anyone reading the docs of those sources can write the same |
| Feature engineering | Yes | Standard signal processing |
| ML training code | Yes | Mostly scikit-learn + standard practices |
| Model architecture decisions | Yes | Documented in model card; published methodology is the credibility moat |
| Production model **artifact** | No | Recreating this from scratch takes weeks of pipeline operations |
| Advisory URL mapping | No | Hand-curated, error-prone to recreate, real labor was invested |
| Web app UI | No | Brand + UX is the differentiation users see |
| Mobile app | No | App Store distribution + brand |

The "moat" sits in the private repos. The "credibility" sits in the public repo. They reinforce each other.

## Migration steps (in order)

### Phase 1 — Add license, no code moves yet (this week, 30 min)

1. `LICENSE` file (Apache 2.0) — done ✓
2. Add copyright header to `backend/app/__init__.py`:
   ```python
   # Copyright 2026 Kyle Choi
   # Licensed under the Apache License, Version 2.0
   ```
3. Update README to clarify open-core strategy
4. Commit + push. **No URLs break, no deployments break.**

### Phase 2 — Move sensitive artifacts to private storage (next week, 2-3 hours)

1. Create new private repo `<private-repo>`
2. Move via `git mv`:
   - `data/curated/serving.sqlite` → `<private-repo>/data/`
   - `data/curated/production_model.json` → `<private-repo>/data/`
   - `data/curated/model_card.md` — KEEP public (it's marketing)
   - `data/curated/system_health.json` — keep public (transparency)
3. Update CI/CD: daily-forecast workflow needs read/write access to the private repo (deploy key) instead of committing to itself
4. Update Render backend: read serving.sqlite from S3 or a private repo URL instead of from local checkout
5. Backend deploys still work because the API just needs to read the file

### Phase 3 — Move web to private repo (~half day)

1. Create `kylechoi101/shorelife-web`
2. `git filter-repo --path web/` to extract `web/` with its full history
3. Push to the new private repo
4. Move `.github/workflows/deploy-web.yml` to the new private repo
5. Set up GitHub Pages or move web hosting to Vercel/Cloudflare Pages (the private repo can still deploy to a public site)
6. **Domain stays the same** — the public URL doesn't change, just the source code is private now
7. After verifying deploys work, `git rm -r web/` from the public repo + push

### Phase 4 — Move mobile to private repo (~half day)

1. Create `kylechoi101/shorelife-mobile`
2. `git filter-repo --path mobile/` for full history
3. Push to private repo
4. Update `eas.json` if it references the public repo
5. Future EAS builds work from the private repo
6. `git rm -r mobile/` from the public repo + push

### Phase 5 — Polish the public repo's pitch (~1 hour)

1. Update README: lead with **research transparency**, link to model card, list publications/citations as they come in
2. Add a CONTRIBUTING.md
3. Add a CODE_OF_CONDUCT.md
4. Pin the model card in the repo description
5. Mark relevant good-first-issues for academic contributors

## What this is worth

- **Public credibility**: scientists, journalists, surf clubs trust an open methodology
- **Competitive defensibility**: cloners can't replicate the artifact, the UX, or the brand
- **Investor/acquirer story**: clean IP allocation (public open-source vs proprietary product) makes a due diligence pass simpler
- **Optionality**: if you ever want to fully close it, you do it from the private repos; the public one stays as the "research version"

## What this is NOT worth

- Don't bother changing the public repo's name — it's already cited, just rename the public-facing surface ("Shorelife — open methodology")
- Don't migrate git history if it's a hassle. A clean cut is fine. People who care about history can browse the old repo.
- Don't apply for trademark unless you start B2B sales (~$700 if you do)
