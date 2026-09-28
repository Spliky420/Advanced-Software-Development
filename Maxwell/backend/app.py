import os
import sqlite3
from flask import Flask, jsonify, request
import requests
import json
import re

# Import shared local services
import sys
from pathlib import Path

# Add shared-local-services to path
shared_services_path = Path(__file__).parent.parent.parent / "shared-local-services"
sys.path.append(str(shared_services_path))

# Import the extended agentic loop
try:
    from agentic_loop_mixin import create_maxwell_glossary_loop
    AGENTIC_LOOP_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import agentic loop mixin: {e}")
    AGENTIC_LOOP_AVAILABLE = False

# Fallback to direct Ollama if services unavailable
OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:0.5b')

# Flask application setup
app = Flask(__name__)

# Enable CORS for all routes (allows frontend on port 8020 to call backend on 8021)
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Financial term validator - basic check to prevent non-financial terms
def is_financial_term(term):
    """
    Basic validation to check if term appears to be financial-related.
    Returns True if term passes financial relevance check, False otherwise.
    """
    if not term or not isinstance(term, str):
        return False

    term_lower = term.lower().strip()

    # Common financial terms and indicators
    financial_indicators = [
        # Accounting
        'asset', 'liability', 'equity', 'revenue', 'expense', 'income', 'profit', 'loss',
        'balance sheet', 'income statement', 'cash flow', 'debit', 'credit', 'ledger',
        'journal', 'accrual', 'depreciation', 'amortization',

        # Investing
        'stock', 'share', 'bond', 'fund', 'etf', 'mutual fund', 'hedge fund', 'index',
        'dividend', 'interest', 'yield', 'return', 'roi', 'roe', 'roa', 'eps', 'pe ratio',
        'market cap', 'volume', 'volatility', 'beta', 'alpha', 'sharpe ratio',
        'bull', 'bear', 'long', 'short', 'leverage', 'margin', 'option', 'future',
        'derivative', 'swap', 'warrant',

        # Banking & Finance
        'loan', 'mortgage', 'credit', 'debit', 'interest rate', 'apr', 'apy',
        'collateral', 'default', 'bank', 'credit union', 'savings', 'checking',
        'wire transfer', 'ach', 'swift', 'iban',

        # Economics
        'inflation', 'deflation', 'stagflation', 'recession', 'depression', 'gdp',
        'cpi', 'ppi', 'unemployment', 'fiscal policy', 'monetary policy',
        'quantitative easing', 'tightening', 'stagflation',

        # Insurance
        'insurance', 'premium', 'deductible', 'coverage', 'claim', 'underwriting',
        'actuarial', 'annuity',

        # Real Estate
        'real estate', 'property', 'rent', 'lease', 'landlord', 'tenant',
        'mortgage', 'equity', 'appraisal',

        # Currencies & Payments
        'currency', 'forex', 'exchange rate', 'dollar', 'euro', 'yen', 'pound',
        'bitcoin', 'cryptocurrency', 'blockchain', 'wallet', 'exchange',
        'paypal', 'venmo', 'apple pay', 'google pay',

        # Business Terms
        'merger', 'acquisition', 'ipo', 'venture capital', 'private equity',
        'angel investor', 'startup', 'incubator', 'accelerator',
        'valuation', 'due diligence', 'term sheet', 'cap table',

        # General financial words
        'finance', 'financial', 'money', 'capital', 'investment', 'economy',
        'economic', 'market', 'trading', 'trade', 'portfolio', 'wealth',
        'budget', 'forecast', 'audit', 'tax', 'tariff', 'duty'
    ]

    # Check if any financial indicator appears in the term
    for indicator in financial_indicators:
        if indicator in term_lower:
            return True

    # Additional checks for common financial patterns
    # Terms ending in common financial suffixes
    financial_suffixes = ['stock', 'bond', 'fund', 'rate', 'ratio', 'index', 'price']
    for suffix in financial_suffixes:
        if term_lower.endswith(suffix):
            return True

    # Terms that are common financial acronyms (2-5 uppercase letters)
    if re.match(r'^[A-Z]{2,5}$', term) and term in ['ROI', 'EPS', 'PE', 'PB', 'APY', 'APR', 'ETF', 'IPO', 'GDP', 'CPI', 'PPI', 'FDA', 'SEC', 'FDIC']:
        return True

    # Reject obvious non-financial categories (basic check)
    non_financial_indicators = [
        # Animals
        'cat', 'dog', 'bird', 'fish', 'horse', 'cow', 'pig', 'sheep', 'goat',
        'lion', 'tiger', 'bear', 'wolf', 'fox', 'rabbit', 'deer',

        # Foods (common)
        'apple', 'banana', 'orange', 'bread', 'milk', 'cheese', 'meat', 'vegetable',
        'fruit', 'cake', 'cookie', 'pizza', 'burger', 'salad',

        # Colors
        'red', 'blue', 'green', 'yellow', 'black', 'white', 'purple', 'orange',
        'pink', 'brown', 'gray',

        # Basic objects
        'table', 'chair', 'door', 'window', 'car', 'bike', 'phone', 'computer',
        'book', 'pen', 'paper', 'clock', 'watch',

        # Nature
        'tree', 'flower', 'grass', 'rock', 'soil', 'water', 'air', 'fire',
        'mountain', 'ocean', 'river', 'lake',

        # People (basic)
        'man', 'woman', 'boy', 'girl', 'child', 'baby', 'king', 'queen',
        'president', 'minister', 'doctor', 'lawyer', 'teacher'
    ]

    # If term exactly matches a known non-financial item, reject
    if term_lower in non_financial_indicators:
        return False

    # Default: allow terms that aren't obviously non-financial
    # (Better to allow some false positives than block legitimate financial terms)
    return True

# Helper function to normalize terms for consistent storage and display
def normalize_term(term):
    """
    Normalize term for storage and comparison.
    Financial terms are conventionally stored in uppercase for proper sorting.
    """
    if not term or not isinstance(term, str):
        return term
    return term.upper().strip()

# Database configuration
DATABASE = os.environ.get('DATABASE', os.path.join(os.path.dirname(__file__), '..', 'database', 'glossary.sqlite'))

# Check if running in test/CI environment
def is_test_environment():
    """Check if running in test or CI environment"""
    return (
        app.testing or
        os.environ.get('CI') == 'true' or
        os.environ.get('TESTING') == 'true' or
        os.environ.get('FLASK_ENV') == 'testing'
    )

# Initialize shared local MCP agentic loop for glossary lookups
def get_glossary_agentic_loop():
    """Get or create the Maxwell glossary agentic loop instance"""
    # Return None in test environment to use mocks
    if is_test_environment():
        return None

    if not hasattr(get_glossary_agentic_loop, '_instance'):
        if AGENTIC_LOOP_AVAILABLE:
            get_glossary_agentic_loop._instance = create_maxwell_glossary_loop(
                mcp_server_url="http://localhost:8090",
                rag_server_url="http://localhost:8091",
                enable_mcp_validation=True,
                enable_rag_validation=True,
                strict_mode=False,  # Either MCP or RAG validation can pass
                confidence_threshold=0.3
            )
        else:
            get_glossary_agentic_loop._instance = None
    return get_glossary_agentic_loop._instance

# Mock agentic loop for testing
class MockGlossaryAgenticLoop:
    """Mock agentic loop for testing environment"""

    def run_extended_loop(self, term, initial_definition="", generate_definition_func=None):
        """Return a mock result for testing"""
        # Use initial definition if provided and valid, otherwise generate a mock one
        if initial_definition and initial_definition.strip() and initial_definition != "Error generating definition.":
            final_definition = initial_definition
            source = "database"
        else:
            # Generate a simple mock definition
            final_definition = f"A financial term related to {term}. This is a mock definition for testing purposes."
            source = "mock"

        return {
            "term": term,
            "initial_definition": initial_definition,
            "phases": {
                "plan": {
                    "phase": "plan",
                    "description": f"Plan to define financial term '{term}' using MCP and RAG validation (MOCK)",
                    "term": term,
                    "has_initial_definition": bool(initial_definition and initial_definition.strip())
                },
                "act": {
                    "phase": "act",
                    "description": f"Generated mock definition for testing (source: {source})",
                    "source": source,
                    "definition": final_definition,
                    "llm_called": False
                },
                "observe": {
                    "phase": "observe",
                    "description": f"Observed mock definition for term '{term}'",
                    "term": term,
                    "definition_preview": final_definition[:50] + "..." if len(final_definition) > 50 else final_definition,
                    "definition_length": len(final_definition)
                },
                "validate_mcp": {
                    "passed": True,
                    "confidence": 0.95,
                    "details": {"mock": True, "note": "MCP validation passed in test mode"}
                },
                "validate_rag": {
                    "passed": True,
                    "confidence": 0.90,
                    "details": {"mock": True, "note": "RAG validation passed in test mode"}
                },
                "adapt": {
                    "phase": "adapt",
                    "description": f"Adapted definition based on MCP/RAG validation results (MOCK)",
                    "mcp_validation_passed": True,
                    "rag_validation_passed": True,
                    "strict_mode": False,
                    "should_use_definition": True,
                    "adaptation_note": "Definition passed validation(s) (MOCK)",
                    "final_definition": final_definition,
                    "confidence_score": 0.92
                }
            },
            "validation_results": {
                "mcp": {"passed": True, "confidence": 0.95, "details": {"mock": True}},
                "rag": {"passed": True, "confidence": 0.90, "details": {"mock": True}},
                "overall_confidence": 0.92
            }
        }

    def get_validation_summary(self):
        """Return mock validation summary"""
        return {
            "mcp_validation": {"passed": True, "confidence": 0.95, "details": {"mock": True}},
            "rag_validation": {"passed": True, "confidence": 0.90, "details": {"mock": True}},
            "overall_confidence": 0.92,
            "strict_mode": False,
            "validation_enabled": {"mcp": True, "rag": True}
        }

# Database connection helper ensuring directory exists
def get_db():
    # Ensure database directory exists
    db_dir = os.path.dirname(DATABASE)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database table if not exists
def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT UNIQUE NOT NULL,
                definition TEXT NOT NULL
            )
        ''')
        conn.commit()

# Enhanced function to generate definition using Ollama (fallback)
def generate_definition_via_ollama(term):
    """Generate definition using direct Ollama call (fallback method)"""
    # Don't call Ollama in test environment
    if is_test_environment():
        return f"Mock definition for {term} - generated in test environment"

    prompt = f"Provide a concise definition for the financial term: {term}"
    ollama_url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }
    try:
        response = requests.post(ollama_url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        definition = result.get('response', '').strip()
        if not definition:
            definition = "Definition not available."
        return definition
    except Exception as e:
        # Log error but don't expose internal details in production
        app.logger.error(f"Ollama error for term {term}: {e}")
        return "Error generating definition."

# Retrieve all glossary terms
@app.route('/api/glossary', methods=['GET'])
def get_glossary():
    with get_db() as conn:
        terms = conn.execute('SELECT term, definition FROM terms ORDER BY term').fetchall()
        return jsonify([{'term': row['term'], 'definition': row['definition']} for row in terms])

# Get single term definition; generate via shared local services if missing and term is financial
@app.route('/api/glossary/<term>', methods=['GET'])
def get_term_definition(term):
    # Normalize the term for consistent storage and comparison
    normalized_term = normalize_term(term)

    # First check if term exists in database (using normalized term)
    with get_db() as conn:
        row = conn.execute('SELECT definition FROM terms WHERE term = ?', (normalized_term,)).fetchone()
        if row:
            definition = row['definition']
            # If we previously stored an error definition, treat as missing and regenerate
            if definition == "Error generating definition.":
                # Fall through to validation and generation logic below
                pass
            else:
                # Return the normalized term (capitalized) for consistent display
                return jsonify({'term': normalized_term, 'definition': definition})

    # Validate if term appears to be financial-related before calling Ollama
    # Use original term for validation to catch case variations in user input
    if not is_financial_term(term):
        return jsonify({
            'error': f'Term "{term}" does not appear to be financial-related. This glossary is for financial terms only.'
        }), 400

    # Get agentic loop (will be mock in test environment)
    agentic_loop = get_glossary_agentic_loop()

    if agentic_loop is not None:
        # Run the extended Plan-Act-Observe-Validate_MCP-Validate_Rag-Adapt loop
        loop_result = agentic_loop.run_extended_loop(
            term=normalized_term,  # Use normalized term for processing
            initial_definition="",  # We'll check database above, so pass empty to trigger generation
            generate_definition_func=generate_definition_via_ollama
        )

        # Extract the final definition from the loop result
        final_definition = loop_result.get('phases', {}).get('adapt', {}).get('final_definition', "Definition unavailable")

        # Store the new term and definition if generation was successful and validation passed
        should_store = (
            final_definition not in [
                "Error generating definition.",
                "Definition not available.",
                "Definition unavailable due to validation failure"
            ] and
            loop_result.get('phases', {}).get('adapt', {}).get('should_use_definition', False)
        )

        if should_store:
            with get_db() as conn:
                try:
                    conn.execute('INSERT INTO terms (term, definition) VALUES (?, ?)', (normalized_term, final_definition))
                    conn.commit()
                except sqlite3.IntegrityError:
                    # Another request might have inserted it meanwhile
                    row = conn.execute('SELECT definition FROM terms WHERE term = ?', (normalized_term,)).fetchone()
                    if row is None:
                        app.logger.error(f"IntegrityError for term {normalized_term} but term not found on select")
                        return jsonify({'term': normalized_term, 'definition': "Error generating definition.", 'error': "Database inconsistency"}), 500
                    final_definition = row['definition']
                except sqlite3.Error as e:
                    app.logger.error(f"SQLite error during insert: {e}")
                    return jsonify({'term': normalized_term, 'definition': "Error generating definition.", 'error': str(e)}), 500

        # Return enhanced response with validation information
        # Use normalized term in response for consistent capitalization
        response_data = {
            'term': normalized_term,
            'definition': final_definition,
            'validation': loop_result.get('validation_results', {}),
            'loop_phases': list(loop_result.get('phases', {}).keys()),
            'source': 'shared_local_services_with_validation'
        }

        # Add source citations if available from RAG validation
        rag_details = loop_result.get('validation_results', {}).get('rag', {}).get('details', {})
        if rag_details and 'retrieved_results' in rag_details:
            response_data['sources'] = [
                {
                    'title': result.get('title', 'Unknown'),
                    'source': result.get('source', 'Unknown'),
                    'score': result.get('score', 0.0)
                }
                for result in rag_details.get('retrieved_results', [])[:3]  # Top 3 sources
            ]

        return jsonify(response_data)

    else:
        # Use mock agentic loop for testing
        mock_loop = MockGlossaryAgenticLoop()
        loop_result = mock_loop.run_extended_loop(
            term=normalized_term,
            initial_definition="",
            generate_definition_func=generate_definition_via_ollama
        )

        final_definition = loop_result.get('phases', {}).get('adapt', {}).get('final_definition', "Mock definition")

        # Store mock definition in database for consistency (using normalized term)
        with get_db() as conn:
            try:
                conn.execute('INSERT OR REPLACE INTO terms (term, definition) VALUES (?, ?)',
                           (normalized_term, final_definition))
                conn.commit()
            except sqlite3.Error:
                pass  # Ignore storage errors in test mode

        # Return enhanced response with validation information (mock)
        response_data = {
            'term': normalized_term,
            'definition': final_definition,
            'validation': loop_result.get('validation_results', {}),
            'loop_phases': list(loop_result.get('phases', {}).keys()),
            'source': 'mock_shared_local_services_for_testing'
        }

        # Add mock source citations
        response_data['sources'] = [
            {
                'title': 'Financial Dictionary Mock',
                'source': 'Shared Local RAG Server (Mock)',
                'score': 0.95
            },
            {
                'title': 'Investopedia Mock',
                'source': 'Financial Knowledge Base (Mock)',
                'score': 0.87
            }
        ]

        return jsonify(response_data)


# Update definition for existing term
@app.route('/api/glossary/<term>', methods=['PUT'])
def update_term(term):
    data = request.get_json()
    if not data or 'definition' not in data:
        return jsonify({'error': 'Missing definition in request body'}), 400

    new_definition = data['definition'].strip()
    if not new_definition:
        return jsonify({'error': 'Definition cannot be empty'}), 400

    # Normalize the term for database operations
    normalized_term = normalize_term(term)

    try:
        with get_db() as conn:
            # Check if term exists (using normalized term)
            row = conn.execute('SELECT definition FROM terms WHERE term = ?', (normalized_term,)).fetchone()
            if not row:
                return jsonify({'error': f'Term "{term}" not found'}), 404

            # Update the definition
            conn.execute('UPDATE terms SET definition = ? WHERE term = ?', (new_definition, normalized_term))
            conn.commit()
    except sqlite3.Error as e:
        app.logger.error(f"SQLite error during update: {e}")
        return jsonify({'error': 'Database error'}), 500

    # Return the normalized term for consistent display
    return jsonify({'term': normalized_term, 'definition': new_definition})


# Delete term
@app.route('/api/glossary/<term>', methods=['DELETE'])
def delete_term(term):
    # Normalize the term for database operations
    normalized_term = normalize_term(term)

    try:
        with get_db() as conn:
            # Check if term exists (using normalized term)
            row = conn.execute('SELECT definition FROM terms WHERE term = ?', (normalized_term,)).fetchone()
            if not row:
                return jsonify({'error': f'Term "{term}" not found'}), 404

            # Delete the term
            conn.execute('DELETE FROM terms WHERE term = ?', (normalized_term,))
            conn.commit()
    except sqlite3.Error as e:
        app.logger.error(f"SQLite error during delete: {e}")
        return jsonify({'error': 'Database error'}), 500

    return jsonify({'message': f'Term "{term}" deleted successfully'})


# Health check endpoint that includes service status
@app.route('/health', methods=['GET'])
def health_check():
    """Extended health check that includes shared local service status"""
    try:
        with get_db() as conn:
            conn.execute('SELECT 1')
            db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    # Check if we're in test environment
    test_mode = is_test_environment()

    # Check shared local services availability (only in non-test mode)
    services_status = {}
    if not test_mode and AGENTIC_LOOP_AVAILABLE:
        try:
            # Try to connect to shared local services
            mcp_response = requests.get("http://localhost:8090/health", timeout=2)
            rag_response = requests.get("http://localhost:8091/health", timeout=2)
            services_status = {
                "mcp_server": "healthy" if mcp_response.status_code == 200 else "unreachable",
                "rag_server": "healthy" if rag_response.status_code == 200 else "unreachable"
            }
        except Exception:
            services_status = {
                "mcp_server": "unreachable",
                "rag_server": "unreachable"
            }
    else:
        services_status = {
            "mcp_server": "mocked_in_test_mode",
            "rag_server": "mocked_in_test_mode"
        }

    return jsonify({
        'status': 'healthy' if db_status == 'healthy' else 'unhealthy',
        'database': db_status,
        'test_mode': test_mode,
        'shared_local_services': services_status,
        'agentic_loop_available': AGENTIC_LOOP_AVAILABLE and not test_mode,
        'timestamp': str(__import__('datetime').datetime.now())
    }), 200 if db_status == 'healthy' else 503


if __name__ == '__main__':
    # Initialize database and run Flask app
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)