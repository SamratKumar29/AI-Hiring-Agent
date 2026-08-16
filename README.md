# AI Hiring Agent

A comprehensive monorepo for AI-powered job hunting, resume optimization, and application tracking. This project combines multiple specialized tools into a unified workflow for modern job searching.

## 🏗️ Architecture

```
AI-Hiring-Agent/
├── Resume-Matcher/          # Resume tailoring & Kanban application tracker
│   ├── apps/backend/        # FastAPI + Python 3.13+, SQLAlchemy, LiteLLM
│   └── apps/frontend/       # Next.js 15 + React 19, Tailwind CSS v4
├── ai-job-scraper/          # FastAPI job scraping microservice
├── job-scraper/             # Multi-source job scraper with Supabase
├── career-ops/              # AI-powered job search automation (Node.js)
├── integration/             # Supabase sync & migration scripts
└── venv/                    # Shared Python virtual environment (gitignored)
```

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- uv (recommended) or pip
- Playwright browsers: `playwright install chromium`

### Setup

```bash
# Clone and enter
git clone https://github.com/SamratKumar29/AI-Hiring-Agent.git
cd AI-Hiring-Agent

# Create and activate shared venv
python3 -m venv venv
source venv/bin/activate

# Install all Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Install Node.js dependencies for each subproject
cd Resume-Matcher/apps/frontend && npm install
cd ../../../career-ops && npm install
```

## 📦 Subprojects

### 1. Resume-Matcher
**AI-powered resume tailoring with Kanban application tracker**

- **Backend**: FastAPI, SQLAlchemy 2.0 (async), SQLite, LiteLLM (multi-provider AI), markitdown, Playwright
- **Frontend**: Next.js 15, React 19, Tailwind CSS v4, Swiss International Style design system
- **Features**: Resume parsing, JD matching, diff-based improvements, cover letters, PDF generation, application tracker

```bash
# Backend
cd Resume-Matcher/apps/backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd Resume-Matcher/apps/frontend
npm run dev
```

### 2. ai-job-scraper
**FastAPI microservice for job scraping**

```bash
cd ai-job-scraper
source ../../venv/bin/activate
uvicorn main:app --reload --port 8001
```

### 3. job-scraper
**Multi-source job scraper with Supabase persistence**

Supports: Greenhouse, Lever, Ashby, Workday, iCIMS, and more

```bash
cd job-scraper
source ../venv/bin/activate
python main.py
```

### 4. career-ops
**AI-powered job search automation pipeline (Node.js/TypeScript)**

- Portal scanning (Greenhouse, Ashby, Lever, Workday, Interamt)
- Offer evaluation & comparison
- CV/PDF generation (HTML + LaTeX)
- Application tracking & follow-ups
- Interview prep & debriefing
- Salary analysis & negotiation

```bash
cd career-ops
npm install
# Run modes via CLI
node scan.mjs                    # Scan portals
node oferta.mjs <url>            # Evaluate offer
node pdf.mjs                     # Generate CV
node tracker.mjs                 # Manage applications
```

### 5. integration
**Supabase sync & database migration scripts**

## 🛠️ Development

### Running Tests

```bash
# Resume-Matcher backend
cd Resume-Matcher/apps/backend && uv run pytest

# Resume-Matcher frontend
cd Resume-Matcher/apps/frontend && npm run test

# career-ops
cd career-ops && node test-all.mjs
```

### Code Quality

```bash
# Python (all projects use shared venv)
cd Resume-Matcher/apps/backend && uv run ruff check .
cd Resume-Matcher/apps/backend && uv run mypy .

# TypeScript
cd Resume-Matcher/apps/frontend && npm run lint
cd Resume-Matcher/apps/frontend && npm run format
cd career-ops && npm run lint
```

## 🔧 Configuration

Each subproject has its own configuration:

| Project | Config Files |
|---------|-------------|
| Resume-Matcher | `apps/backend/.env`, `apps/frontend/.env.local` |
| ai-job-scraper | `.env` |
| job-scraper | `.env` |
| career-ops | `config/profile.yml`, `portals.yml`, `.env` |

Copy `.env.example` to `.env` in each project and fill in your API keys.

## 📋 Requirements

See [requirements.txt](requirements.txt) for consolidated Python dependencies.

Key dependencies:
- **Web**: FastAPI, Uvicorn, Starlette
- **AI**: LiteLLM, OpenAI, Anthropic, Google GenAI, Ollama
- **Database**: SQLAlchemy 2.0, aiosqlite, Supabase, TinyDB
- **Parsing**: markitdown, pdfplumber, python-docx, playwright
- **Data**: Pydantic v2, pydantic-settings, httpx, requests
- **Utils**: python-dotenv, cryptography, python-multipart

## 🌿 Branch Strategy

- `main` - Production ready
- Feature branches from `main`
- PRs required for all changes

## 📄 License

MIT License - see individual subproject LICENSE files for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a PR

## 📚 Documentation

- [Resume-Matcher Docs](Resume-Matcher/docs/agent/README.md)
- [career-ops Docs](career-ops/docs/)
- [API Contracts](Resume-Matcher/docs/agent/apis/)

---

**Built for developers, by developers** — Automate the tedious parts of job hunting so you can focus on what matters: finding the right role.