import os
import sqlite3
from flask import Flask, jsonify, request
import requests
import json
import re

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

# Database configuration
DATABASE = os.environ.get('DATABASE', os.path.join(os.path.dirname(__file__), '..', 'database', 'glossary.sqlite'))
OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:0.5b')

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
            if row:
                definition = row['definition']

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

    with get_db() as conn:
        # Check if term exists
        row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
        if not row:
            return jsonify({'error': f'Term "{term}" not found'}), 404

        # Update the definition
        conn.execute('UPDATE terms SET definition = ? WHERE term = ?', (new_definition, term))
        conn.commit()

    return jsonify({'term': term, 'definition': new_definition})


# Delete term
@app.route('/api/glossary/<term>', methods=['DELETE'])
def delete_term(term):
    with get_db() as conn:
        # Check if term exists
        row = conn.execute('SELECT definition FROM terms WHERE term = ?', (term,)).fetchone()
        if not row:
            return jsonify({'error': f'Term "{term}" not found'}), 404

        # Delete the term
        conn.execute('DELETE FROM terms WHERE term = ?', (term,))
        conn.commit()

    return jsonify({'message': f'Term "{term}" deleted successfully'})

if __name__ == '__main__':
    # Initialize database and run Flask app
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)