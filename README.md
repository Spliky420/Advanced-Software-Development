# Advanced-Software-Development
ASD 2026 Project

This repository contains the financial glossary feature built by Maxwell.

## Services
- **Backend**: Python Flask API serving glossary terms at `/api/glossary` and `/api/glossary/<term>`
  - Uses SQLite database for storage
  - Uses Ollama to generate definitions for missing financial terms
  - Includes validation to prevent non-financial terms from being processed via Ollama
- **Frontend**: Static HTML/JavaScript client with full CRUD operations:
  - Add new terms (with Ollama-generated definitions for financial terms)
  - Edit existing term definitions
  - Delete terms
  - Validation feedback for non-financial terms
- **Database**: SQLite database (one per microservice)

## Running the stack
```bash
docker compose up --build
```
Then visit http://localhost:8020 to see the glossary.

## Features
- **Financial Term Validation**: Backend validates terms before calling Ollama to ensure only financial terms are processed
- **Full CRUD Operations**: Create, Read, Update, Delete glossary terms
- **AI-Powered Definitions**: Missing financial terms get definitions generated via Ollama
- **Shared Reference Data**: No user scoping (Release 0 specification)
- **Ollama Integration**: LLM access exclusively via Ollama at `http://ollama:11434`

## Notes
- All LLM access goes through Ollama service (shared)
- Port range: 8020-8029 (frontend 8020, backend 8021)
- The backend follows the specification: shared reference data (no user_id), AI-Mode for missing terms via Ollama (with financial validation)
- Non-financial terms are rejected with a clear error message instead of being sent to Ollama

## Environment Variables
The backend reads configuration from environment variables with sensible defaults.
For convenience, an example file `.env.example` is provided. Copy it to `.env` if you need to override the defaults:

```bash
cp .env.example .env
```

Then edit `.env` as needed (e.g., to switch to the demo model `llama3.1:8b`).
