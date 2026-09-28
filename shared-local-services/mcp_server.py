#!/usr/bin/env python3
"""
Shared Local MCP Server for Financial Context and Validation
Non-containerized service running on host machine
"""

import json
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
from pathlib import Path


class FinancialMCPHandler(BaseHTTPRequestHandler):

    # Load financial knowledge base at startup
    KNOWLEDGE_BASE = {}

    def __init__(self, *args, **kwargs):
        # Load knowledge base once per handler instance
        if not FinancialMCPHandler.KNOWLEDGE_BASE:
            FinancialMCPHandler.KNOWLEDGE_BASE = self._load_knowledge_base()
        super().__init__(*args, **kwargs)

    def _load_knowledge_base(self):
        """Load financial terms, relationships, and rules from JSON files"""
        kb_path = Path(__file__).parent / "financial_knowledge_base"
        knowledge_base = {}

        try:
            # Load terms
            with open(kb_path / "terms.json", 'r') as f:
                terms_data = json.load(f)
                knowledge_base['terms'] = {term['term']: term for term in terms_data['financial_terms']}

            # Load relationships
            with open(kb_path / "relationships.json", 'r') as f:
                knowledge_base['relationships'] = json.load(f)

            # Load rules
            with open(kb_path / "rules.json", 'r') as f:
                knowledge_base['rules'] = json.load(f)

        except Exception as e:
            print(f"Warning: Could not load knowledge base: {e}")
            # Provide minimal fallback
            knowledge_base = {
                'terms': {},
                'relationships': {},
                'rules': {
                    'validation_rules': {
                        'financial_term_indicators': {
                            'strong_indicators': ['stock', 'bond', 'fund', 'invest'],
                            'weak_indicators': ['price', 'value', 'market']
                        }
                    }
                }
            }

        return knowledge_base

    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == "/health":
            self._handle_health()
        elif path.startswith("/context/financial"):
            self._handle_financial_context(parsed_path)
        else:
            self._handle_not_found()

    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""

        if path == "/validate/term":
            self._handle_validate_term(post_data)
        elif path == "/enrich/query":
            self._handle_enrich_query(post_data)
        else:
            self._handle_not_found()

    def _handle_health(self):
        """Health check endpoint"""
        self._send_json_response({
            "status": "healthy",
            "service": "Shared Local MCP Server",
            "version": "1.0.0",
            "knowledge_base_terms": len(self.KNOWLEDGE_BASE.get('terms', {}))
        })

    def _handle_financial_context(self, parsed_path):
        """Return financial domain context"""
        query_params = parse_qs(parsed_path.query)
        domain = query_params.get('domain', [None])[0]

        context = {
            "financial_domains": self.KNOWLEDGE_BASE.get('rules', {}).get('context_enrichment', {}).get('financial_domains', []),
            "common_contexts": self.KNOWLEDGE_BASE.get('rules', {}).get('context_enrichment', {}).get('common_contexts', []),
            "total_terms": len(self.KNOWLEDGE_BASE.get('terms', {}))
        }

        if domain and domain in self.KNOWLEDGE_BASE.get('terms', {}):
            context['specific_term'] = self.KNOWLEDGE_BASE['terms'][domain]

        self._send_json_response(context)

    def _handle_validate_term(self, post_data):
        """Validate if term is financial-related"""
        try:
            data = json.loads(post_data) if post_data else {}
            term = data.get('term', '').strip()

            if not term:
                self._send_json_response({
                    "valid": False,
                    "error": "Term is required",
                    "confidence": 0.0
                }, status_code=400)
                return

            validation_result = self._validate_financial_term(term)
            self._send_json_response(validation_result)

        except json.JSONDecodeError:
            self._send_json_response({
                "valid": False,
                "error": "Invalid JSON",
                "confidence": 0.0
            }, status_code=400)
        except Exception as e:
            self._send_json_response({
                "valid": False,
                "error": str(e),
                "confidence": 0.0
            }, status_code=500)

    def _handle_enrich_query(self, post_data):
        """Enrich query with financial context"""
        try:
            data = json.loads(post_data) if post_data else {}
            query = data.get('query', '').strip()

            if not query:
                self._send_json_response({
                    "error": "Query is required",
                    "enriched_query": query,
                    "context_added": []
                }, status_code=400)
                return

            enrichment = self._enrich_query_with_financial_context(query)
            self._send_json_response(enrichment)

        except json.JSONDecodeError:
            self._send_json_response({
                "error": "Invalid JSON",
                "enriched_query": "",
                "context_added": []
            }, status_code=400)
        except Exception as e:
            self._send_json_response({
                "error": str(e),
                "enriched_query": "",
                "context_added": []
            }, status_code=500)

    def _validate_financial_term(self, term):
        """Validate if a term is financial-related using knowledge base rules"""
        if not term:
            return {"valid": False, "confidence": 0.0, "reason": "Empty term"}

        term_lower = term.lower().strip()

        # Check exact matches in knowledge base terms
        if term_lower in self.KNOWLEDGE_BASE.get('terms', {}):
            term_info = self.KNOWLEDGE_BASE['terms'][term_lower]
            return {
                "valid": True,
                "confidence": term_info.get('confidence', 0.9),
                "reason": f"Found in knowledge base: {term_info.get('definition', '')}",
                "term_info": term_info
            }

        # Apply validation rules
        rules = self.KNOWLEDGE_BASE.get('rules', {}).get('validation_rules', {})
        indicators = rules.get('financial_term_indicators', {})
        strong_indicators = set(indicators.get('strong_indicators', []))
        weak_indicators = set(indicators.get('weak_indicators', []))

        exclusions = rules.get('non_financial_exclusions', {})
        exact_matches = set(exclusions.get('exact_matches', []))
        prefix_exclusions = exclusions.get('prefix_exclusions', [])

        scoring = rules.get('scoring', {})
        strong_weight = scoring.get('strong_indicator_weight', 0.4)
        weak_weight = scoring.get('weak_indicator_weight', 0.2)
        exact_penalty = scoring.get('exact_non_financial_penalty', 0.5)
        min_threshold = scoring.get('minimum_confidence_threshold', 0.3)

        # Check for exact non-financial matches
        if term_lower in exact_matches:
            return {
                "valid": False,
                "confidence": 0.0,
                "reason": f"Term '{term}' is explicitly non-financial"
            }

        # Check prefix exclusions
        for prefix in prefix_exclusions:
            if term_lower.startswith(prefix):
                return {
                    "valid": False,
                    "confidence": 0.0,
                    "reason": f"Term '{term}' has non-financial prefix '{prefix}'"
                }

        # Calculate confidence based on indicators
        confidence = 0.0
        matched_indicators = []

        # Check for strong indicators (exact word matches)
        for indicator in strong_indicators:
            if indicator in term_lower.split():
                confidence += strong_weight
                matched_indicators.append(f"strong:{indicator}")

        # Check for weak indicators (substring matches)
        for indicator in weak_indicators:
            if indicator in term_lower:
                confidence += weak_weight
                matched_indicators.append(f"weak:{indicator}")

        # Length normalization (very short or long terms less likely to be financial)
        length_factor = min(1.0, len(term) / 20.0)  # Normalize to 20 chars
        confidence *= (0.5 + 0.5 * length_factor)  # Boost for reasonable length

        # Ensure confidence is in [0, 1] range
        confidence = max(0.0, min(1.0, confidence))

        # Determine validity based on threshold
        valid = confidence >= min_threshold

        reason_parts = []
        if matched_indicators:
            reason_parts.append(f"Matched indicators: {', '.join(matched_indicators)}")
        else:
            reason_parts.append("No financial indicators found")

        reason_parts.append(f"Confidence: {confidence:.2f}")

        return {
            "valid": valid,
            "confidence": round(confidence, 2),
            "reason": "; ".join(reason_parts),
            "matched_indicators": matched_indicators
        }

    def _enrich_query_with_financial_context(self, query):
        """Enrich a query with financial context from knowledge base"""
        query_lower = query.lower()
        context_added = []

        # Find relevant financial terms in the query
        found_terms = []
        for term, term_info in self.KNOWLEDGE_BASE.get('terms', {}).items():
            if term in query_lower:
                found_terms.append({
                    "term": term,
                    "definition": term_info.get('definition', ''),
                    "category": term_info.get('category', ''),
                    "confidence": term_info.get('confidence', 0.0),
                    "related_terms": term_info.get('related_terms', [])
                })
                context_added.append(term)

        # Add domain context if financial terms found
        domains_found = set()
        if found_terms:
            # Check which domains these terms belong to
            for term_info in self.KNOWLEDGE_BASE.get('terms', {}).values():
                category = term_info.get('category', '')
                if category:
                    domains_found.add(category)

        enriched_parts = [query]

        if found_terms:
            enriched_parts.append("\n\nFinancial Context:")
            for term_info in found_terms[:3]:  # Limit to top 3 terms
                enriched_parts.append(f"- {term_info['term']}: {term_info['definition']}")

        if domains_found:
            enriched_parts.append(f"\nRelevant Financial Domains: {', '.join(sorted(domains_found))}")

        enriched_query = "\n".join(enriched_parts)

        return {
            "original_query": query,
            "enriched_query": enriched_query,
            "context_added": list(set(context_added)),  # Remove duplicates
            "found_terms": found_terms,
            "domains_found": list(domains_found),
            "confidence": min(0.9, 0.3 + len(found_terms) * 0.2) if found_terms else 0.1
        }

    def _handle_not_found(self):
        """Handle 404 Not Found"""
        self._send_json_response({
            "error": "Endpoint not found",
            "available_endpoints": [
                "GET /health",
                "GET /context/financial",
                "POST /validate/term",
                "POST /enrich/query"
            ]
        }, status_code=404)

    def _send_json_response(self, data, status_code=200):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

        response_json = json.dumps(data, indent=2)
        self.wfile.write(response_json.encode('utf-8'))

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Override to reduce log noise"""
        pass


def run_server(port=8090):
    """Run the MCP server on specified port"""
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, FinancialMCPHandler)
    print(f"Shared Local MCP Server running on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down MCP server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()