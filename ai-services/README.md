# ai-services/

Required root directory (spec 7.1). Holds the configuration and documentation
for the shared AI service the project runs on, as distinct from the five
students' feature microservices, which live in their own top-level
directories.

Every LLM call in this project goes to one shared Ollama container defined in
the root `docker-compose.yml`. No student runs their own model service, and
no commercial or external AI API is called at runtime (see `CLAUDE.md`).

## Contents

- [`ai-mode/`](ai-mode/README.md) — how the shared Ollama service is
  configured: image, port, volume, healthcheck, the environment variables each
  backend reads, and how to pull a model into the container.

## What is not here

The Ollama service itself is declared in the root `docker-compose.yml`, not in
this directory, and the model tag defaults live in `.env` / `.env.example` at
the repository root. This directory documents that setup; it does not
duplicate or override it. There are no runnable files here.
