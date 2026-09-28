# Shared Local Services for Personal Finance Assistant

This directory contains shared local (non-containerized) services that provide enhanced AI capabilities to all student features in the ASD 2026 project.

## Overview

These services implement the requirements for:
1. **Shared Local MCP Server** - Provides financial context and validation via Model Context Protocol
2. **Shared Local RAG Server** - Provides retrieval-augmented generation capabilities for financial documents
3. **Extended Agentic Loop** - Enhanced Plan-Act-Observe-Adapt loop with MCP and RAG validation modes

## Services

### 1. MCP Server (`mcp_server.py`)
A non-containerized HTTP server running on `http://localhost:8090` that provides:
- **GET /health** - Health check
- **GET /context/financial** - Returns financial domain context
- **POST /validate/term** - Validates if a term is financial-related
- **POST /enrich/query** - Enriches queries with financial context

### 2. RAG Server (`rag_server.py`)
A non-containerized HTTP server running on `http://localhost:8091` that provides:
- **GET /health** - Health check
- **POST /retrieve** - Retrieves relevant financial document chunks for a query
- **POST /embed** - Embeds text using local embedding function

### 3. Extended Agentic Loop (`agentic_loop_mixin.py`)
Provides `MaxwellGlossaryAgenticLoop` class that implements:
- **PLAN** - Determine scope and parameters
- **ACT** - Perform computations (definition generation)
- **OBSERVE** - Analyze results
- **VALIDATE_MCP** - Check against MCP financial context
- **VALIDATE_RAG** - Check against RAG retrieved context
- **ADAPT** - Generate final response using validation results

## Financial Knowledge Base

The services use a curated financial knowledge base located in `financial_knowledge_base/`:
- `terms.json` - Core financial terms with definitions and relationships
- `relationships.json` - Term relationships and hierarchies
- `rules.json` - Validation rules and context enrichment guidelines

## Usage in Maxwell Backend

The Maxwell backend (`Maxwell/backend/app.py`) automatically:
1. Detects when running in test/CI environment
2. In test mode: Uses mock services for fast, reliable testing
3. In development/production: Connects to the shared local services
4. Falls back to direct Ollama calls if services are unavailable

## Environment Variables

The services check for these environment variables:
- `CI` - If set to "true", enables test mode
- `TESTING` - If set to "true", enables test mode
- `FLASK_ENV` - If set to "testing", enables test mode

## Development Setup

To run the shared local services for development:

```bash
# Start MCP server (terminal 1)
cd shared-local-services
python mcp_server.py

# Start RAG server (terminal 2)
cd shared-local-services
python rag_server.py

# Run Maxwell backend (will auto-discover services)
cd Maxwell/backend
python app.py
```

## Testing

During CI/CD or testing, the Maxwell backend automatically uses mock implementations:
- No external service dependencies
- Fast, deterministic responses
- Consistent test results

To manually test with mocks:
```bash
cd Maxwell/backend
export TESTING=true
python app.py
```

## Validation & Confidence

All AI responses include:
- **Source citations** - Attribution to retrieved documents or knowledge base
- **Confidence categories** - Quantitative confidence scores (0.0-1.0)
- **Validation results** - Detailed MCP and RAG validation outcomes
- **Loop phases** - Transparent view of the Plan-Act-Observe-Validate-Adapt process

## Dependencies

All services use only Python standard library:
- `http.server` - For HTTP endpoints
- `json` - For data serialization
- `sqlite3` - For RAG document storage (RAG server only)
- `math` - For similarity calculations
- `re` - For pattern matching
- `threading` - For concurrent operations
- `pathlib`, `urllib.parse` - For URL and path handling

No external dependencies are required for basic operation.