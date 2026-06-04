# CI/CD — GitHub Actions

Each repo has a workflow at `.github/workflows/ci.yml` that runs on **push** and **pull requests** to `main`, `master`, `feature-fix`, and `develop`.

## Workflows

| Repo | Workflow | What it does |
|------|----------|----------------|
| **Backend** | `Backend CI` | Python 3.13, `pytest`, app import smoke test (SQLite, mock payments) |
| **Frontend** | `Frontend CI` | Node 20, `npm run build` (required), ESLint (informational) |
| **Mobile** | `Mobile CI` | Flutter stable, `analyze`, `test`, web release build smoke |

## Enable on GitHub

1. Push these files to GitHub (each repository separately).
2. Open **Actions** tab — workflows run automatically.
3. Add a **branch protection rule** (optional): require `Backend CI` / `Frontend CI` / `Mobile CI` before merge.

## Deployment (CD)

Production deploys are handled by **Vercel** (already configured via `vercel.json` in each repo):

| App | Typical URL |
|-----|-------------|
| API | `https://mrm-rental-manager-backend.vercel.app` |
| Web | `https://mrm-rental-manager-frontend-pink.vercel.app` |
| Mobile web | `https://mrm-rental-manager-mobile.vercel.app` |

Connect each GitHub repo to Vercel for automatic deploys on push to `main`.

### Play Store / App Store

CI builds **web** only for mobile. Native AAB/IPA builds run locally or via a separate release workflow with signing secrets.

## Local commands (same as CI)

```bash
# Backend
cd MRM-Rental-Manager-Backend-
export DATABASE_URL=sqlite:///./ci_test.db
export SECRET_KEY=ci-secret-key-for-github-actions-only-32chars
export SKIP_STARTUP_MIGRATIONS=true
pip install -r requirements.txt -r requirements-dev.txt
pytest tests -q

# Frontend
cd MRM-Rental-Manager-Frontend-
npm ci && npm run build

# Mobile
cd MRM-Rental-Manager-Mobile-
flutter pub get && flutter analyze --no-fatal-infos --no-fatal-warnings && flutter test
```
