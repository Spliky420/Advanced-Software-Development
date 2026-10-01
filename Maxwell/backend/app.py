import os
import sqlite3
from flask import Flask, jsonify, request, Response
import requests
import json
import re
import sys

# Flask application setup
app = Flask(__name__)

# Enable CORS for all routes (allows frontend on port 8020 to call backend on 8021)
@app.after_request
def after_request(response):
    print(f"AFTER_REQUEST: Response headers before: {response.headers}", file=sys.stderr, flush=True)
    if 'Access-Control-Allow-Origin' not in response.headers:
        print(f"AFTER_REQUEST: Setting Access-Control-Allow-Origin to *", file=sys.stderr, flush=True)
        response.headers.set('Access-Control-Allow-Origin', '*')
    else:
        print(f"AFTER_REQUEST: Access-Control-Allow-Origin already present: {response.headers.get('Access-Control-Allow-Origin')}", file=sys.stderr, flush=True)
    response.headers.set('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.set('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    print(f"AFTER_REQUEST: Response headers after: {response.headers}", file=sys.stderr, flush=True)
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

# Database configuration
DATABASE = os.environ.get('DATABASE', os.path.join(os.path.dirname(__file__), '..', 'database', 'glossary.sqlite'))
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:0.5b')

# CI/CD feature disabling flags
DISABLE_AI_MODE = os.environ.get('DISABLE_AI_MODE', 'false').lower() == 'true'
DISABLE_MCP_PROXY = os.environ.get('DISABLE_MCP_PROXY', 'false').lower() == 'true'
DISABLE_RAG_PROXY = os.environ.get('DISABLE_RAG_PROXY', 'false').lower() == 'true'

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

# Retrieve all glossary terms
@app.route('/api/glossary', methods=['GET'])
def get_glossary():
    with get_db() as conn:
        terms = conn.execute('SELECT term, definition FROM terms ORDER BY term').fetchall()
        return jsonify([{'term': row['term'], 'definition': row['definition']} for row in terms])

# Get single term definition; generate via Ollama if missing and term is financial
@app.route('/api/glossary/<term>', methods=['GET'])
def get_term_definition(term):
    # First check if term exists in database
    with get_db() as conn:
        row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
        if row:
            definition = row['definition']
            # If we previously stored an error definition, treat as missing and regenerate
            if definition == "Error generating definition.":
                # Fall through to validation and generation logic below
                pass
            else:
                return jsonify({'term': term, 'definition': definition})

    # Validate if term appears to be financial-related before calling Ollama
    if not is_financial_term(term):
        return jsonify({
            'error': f'Term "{term}" does not appear to be financial-related. This glossary is for financial terms only.'
        }), 400

    # Term not found or previous generation failed, generate definition via Ollama
    # Check if AI-Mode is disabled for CI/CD
    if DISABLE_AI_MODE:
        return jsonify({'term': term, 'definition': 'AI-Mode is disabled in CI/CD'}), 503

    prompt = f"Provide a concise definition for the financial term: {term}"
    ollama_url = f"{OLLAMA_BASE_URL}/api/generate"
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
    except Exception as e:
        app.logger.error(f"Ollama error: {e}")
        # Do not store error definition; return error without caching
        return jsonify({'term': term, 'definition': "Error generating definition.", 'error': str(e)}), 500

    # Store the new term and definition
    with get_db() as conn:
        try:
            conn.execute('INSERT INTO terms (term, definition) VALUES (?, ?)', (term, definition))
            conn.commit()
        except sqlite3.IntegrityError:
            # Another request might have inserted it meanwhile
            row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
            if row is None:
                app.logger.error(f"IntegrityError for term {term} but term not found on select")
                return jsonify({'term': term, 'definition': "Error generating definition.", 'error': "Database inconsistency"}), 500
            definition = row['definition']
        except sqlite3.Error as e:
            app.logger.error(f"SQLite error during insert: {e}")
            return jsonify({'term': term, 'definition': "Error generating definition.", 'error': str(e)}), 500

    return jsonify({'term': term, 'definition': definition})


# Update definition for existing term
@app.route('/api/glossary/<term>', methods=['PUT'])
def update_term(term):
    data = request.get_json()
    if not data or 'definition' not in data:
        return jsonify({'error': 'Missing definition in request body'}), 400

    new_definition = data['definition'].strip()
    if not new_definition:
        return jsonify({'error': 'Definition cannot be empty'}), 400

    try:
        with get_db() as conn:
            # Check if term exists
            row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
            if not row:
                return jsonify({'error': f'Term "{term}" not found'}), 404

            # Update the definition
            conn.execute('UPDATE terms SET definition = ? WHERE term = ?', (new_definition, term))
            conn.commit()
    except sqlite3.Error as e:
        app.logger.error(f"SQLite error during update: {e}")
        return jsonify({'error': 'Database error'}), 500

    return jsonify({'term': term, 'definition': new_definition})


# Delete term
@app.route('/api/glossary/<term>', methods=['DELETE'])
def delete_term(term):
    try:
        with get_db() as conn:
            # Check if term exists
            row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
            if not row:
                return jsonify({'error': f'Term "{term}" not found'}), 404

            # Delete the term
            conn.execute('DELETE FROM terms WHERE term = ?', (term,))
            conn.commit()
    except sqlite3.Error as e:
        app.logger.error(f"SQLite error during delete: {e}")
        return jsonify({'error': 'Database error'}), 500

    return jsonify({'message': f'Term "{term}" deleted successfully'})



# MCP Proxy Endpoints
@app.route('/api/mcp/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def mcp_proxy(subpath):
    with open('/tmp/mcp_proxy.log', 'a') as f:
        f.write(f"MCP_PROXY: Called with subpath={subpath}\\n")
    # Check if MCP proxy is disabled for CI/CD
    print(f"DEBUG: DISABLE_MCP_PROXY = {DISABLE_MCP_PROXY}", flush=True)
    if DISABLE_MCP_PROXY:
        return jsonify({'error': 'MCP proxy is disabled in CI/CD environment'}), 503

    # Forward to MCP server Flask app (port 5001)
    mcp_url = f"http://mcp-server:5001/mcp/{subpath}"

    # Prepare headers to forward (excluding hop-by-hop headers)
    headers = {key: value for (key, value) in request.headers if key.lower() not in
               ['host', 'content-length']}

    # Make the request to the MCP server
    resp = requests.request(
        method=request.method,
        url=mcp_url,
        headers=headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False)

    # Create a Flask response with the proxied response's content, status, and headers
    response = Response(
        resp.content,
        status=resp.status_code
    )
    # Copy headers from the MCP server response, excluding hop-by-hop and other headers that should not be proxied
    # We will set CORS headers ourselves based on the request
    skip_headers = {
        'content-length', 'connection', 'keep-alive', 'public',
        'proxy-authenticate', 'proxy-authorization', 'te', 'trailers',
        'transfer-encoding', 'upgrade', 'server', 'date',
        'access-control-origin', 'access-control-headers', 'access-control-methods'
    }
    for key, value in resp.headers.items():
        if key.lower() not in skip_headers:
            response.headers[key] = value
    # Set CORS headers based on the request
    origin = request.headers.get('Origin')
    if origin:
        response.headers.set('Access-Control-Allow-Origin', origin)
        response.headers.set('Vary', 'Origin')
    else:
        response.headers.set('Access-Control-Allow-Origin', '*')
    response.headers.set('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.set('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    # Log the response headers to a file for debugging
    try:
        with open('/tmp/mcp_proxy_response_headers.log', 'a') as f:
            f.write(f"Response headers: {dict(response.headers)}\\n")
    except Exception as e:
        pass
    return response


# RAG Proxy Endpoints
@app.route('/api/rag/refresh', methods=['POST'])
def rag_refresh_proxy():
    # Check if RAG proxy is disabled for CI/CD
    if DISABLE_RAG_PROXY:
        return jsonify({'error': 'RAG proxy is disabled in CI/CD environment'}), 503

    # Forward to RAG server (running on host port 5003)
    rag_url = "http://rag-server:5003/refresh"

    # Prepare headers
    headers = {key: value for (key, value) in request.headers if key.lower() not in
               ['host', 'content-length']}

    # Make the request
    resp = requests.request(
        method=request.method,
        url=rag_url,
        headers=headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False)

    # Create Flask response
    response = Response(
        resp.content,
        status=resp.status_code,
        headers=dict(resp.headers)
    )
    return response

@app.route('/api/rag/retrieve', methods=['POST'])
def rag_retrieve_proxy():
    # Check if RAG proxy is disabled for CI/CD
    if DISABLE_RAG_PROXY:
        return jsonify({'error': 'RAG proxy is disabled in CI/CD environment'}), 503

    rag_url = "http://rag-server:5003/retrieve"

    headers = {key: value for (key, value) in request.headers if key.lower() not in
               ['host', 'content-length']}

    # Make the request
    resp = requests.request(
        method=request.method,
        url=rag_url,
        headers=headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False)

    # Create Flask response
    response = Response(
        resp.content,
        status=resp.status_code,
        headers=dict(resp.headers)
    )
    return response

@app.route('/api/rag/answer', methods=['POST'])
def rag_answer_proxy():
    # Check if RAG proxy is disabled for CI/CD
    if DISABLE_RAG_PROXY:
        return jsonify({'error': 'RAG proxy is disabled in CI/CD environment'}), 503

    rag_url = "http://rag-server:5003/answer"

    headers = {key: value for (key, value) in request.headers if key.lower() not in
               ['host', 'content-length']}

    # Make the request
    resp = requests.request(
        method=request.method,
        url=rag_url,
        headers=headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False)

    # Create Flask response
    response = Response(
        resp.content,
        status=resp.status_code,
        headers=dict(resp.headers)
    )
    return response


# Test route to verify routing is working
@app.route('/api/test', methods=['GET'])
def test_route():
    with open('/tmp/test_route.log', 'a') as f:
        f.write('test_route called\\n')
    return jsonify({'message': 'Test route is working!'}), 200


if __name__ == '__main__':
    # Initialize database and run Flask app
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)