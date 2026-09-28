#!/usr/bin/env python3
"""
Shared Local RAG Server for Financial Document Retrieval
Non-containerized service running on host machine
"""

import json
import math
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import sqlite3
import threading


class RAGHandler(BaseHTTPRequestHandler):

    # Configuration
    DEFAULT_TOP_K = 5
    MIN_SIMILARITY_SCORE = 0.0

    def __init__(self, *args, **kwargs):
        # Initialize database connection
        self.db_path = self._get_database_path()
        super().__init__(*args, **kwargs)

    def _get_database_path(self):
        """Get path to the shared financial documents database"""
        # For now, we'll use Enerel's database path or create a shared one
        db_dir = Path(__file__).parent.parent.parent / "Enerel" / "database"
        db_path = db_dir / "library.db"

        # If the database doesn't exist, we'll create a minimal shared database
        if not db_path.exists():
            return self._create_shared_database()
        return str(db_path)

    def _create_shared_database(self):
        """Create a shared financial documents database if none exists"""
        db_dir = Path(__file__).parent
        db_path = db_dir / "shared_financial_library.db"

        # Create directory if it doesn't exist
        db_dir.mkdir(exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create documents table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT 1,
                title TEXT NOT NULL,
                source TEXT,
                doc_type TEXT,
                published_on TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create chunks table for document text
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding_vector TEXT,  -- JSON serialized vector
                FOREIGN KEY (document_id) REFERENCES documents (id)
            )
        ''')

        # Create embeddings table (separate for efficiency)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id INTEGER NOT NULL,
                model_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chunk_id) REFERENCES document_chunks (id)
            )
        ''')

        conn.commit()
        conn.close()

        # Add some sample financial documents for demonstration
        self._populate_sample_documents(str(db_path))

        return str(db_path)

    def _populate_sample_documents(self, db_path):
        """Add sample financial documents to the database"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if we already have documents
        cursor.execute("SELECT COUNT(*) FROM documents")
        count = cursor.fetchone()[0]

        if count == 0:
            # Add sample financial documents
            sample_docs = [
                {
                    "title": "Understanding ETFs and Index Funds",
                    "source": "Financial Education Guide",
                    "doc_type": "educational",
                    "published_on": "2024-01-15",
                    "content": "Exchange-Traded Funds (ETFs) are investment funds that are traded on stock exchanges, much like stocks. They hold assets such as stocks, commodities, or bonds and generally operate with an arbitrage mechanism designed to keep trading close to its net asset value, though deviations can occur. Most ETFs track an index, such as a stock index or bond index. ETFs offer diversification, low costs, and tax efficiency compared to traditional mutual funds."
                },
                {
                    "title": "Stock Market Basics: How to Invest in Shares",
                    "source": "Investing for Beginners",
                    "doc_type": "educational",
                    "published_on": "2024-02-01",
                    "content": "Stocks represent ownership shares in a corporation. When you buy a company's stock, you're purchasing a piece of that company. Shareholders have a claim on part of the company's assets and earnings. Stocks are also known as shares or equity. There are two main types of stock: common and preferred. Common stock usually gives shareholders voting rights and the potential to receive dividends. Preferred stock typically does not carry voting rights but has a higher claim on assets and earnings than common stock."
                },
                {
                    "title": "Bond Investing: Fixed Income Securities Explained",
                    "source": "Fixed Income Guide",
                    "doc_type": "educational",
                    "published_on": "2024-02-15",
                    "content": "Bonds are fixed-income instruments that represent loans made by investors to borrowers, typically corporations or governments. A bond could be thought of as an I.O.U. between the lender and borrower that includes the details of the loan and its payments. Bonds are used by companies, municipalities, states, and sovereign governments to finance projects and operations. Owners of bonds are debtholders, or creditors, of the issuer. Bond details include the end date when the principal of the loan is due to be paid to the bond owner, and usually includes terms for variable or fixed interest payments made by the issuer."
                }
            ]

            for doc in sample_docs:
                cursor.execute('''
                    INSERT INTO documents (title, source, doc_type, published_on)
                    VALUES (?, ?, ?, ?)
                ''', (doc["title"], doc["source"], doc["doc_type"], doc["published_on"]))

                doc_id = cursor.lastrowid

                # Simple chunking by sentences (for demo purposes)
                sentences = doc["content"].split('. ')
                for i, sentence in enumerate(sentences):
                    if sentence.strip():
                        cursor.execute('''
                            INSERT INTO document_chunks (document_id, chunk_index, chunk_text)
                            VALUES (?, ?, ?)
                        ''', (doc_id, i, sentence.strip()))

            conn.commit()

        conn.close()

    def _cosine_similarity(self, a, b):
        """Compute cosine similarity between two vectors"""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _get_embedding(self, text):
        """Get embedding for text using a simple hash-based approach for demo
        In production, this would call an embedding model like nomic-embed-text
        """
        # Simple deterministic vector based on text hash (for demo only)
        # In real implementation, this would call an external embedding service
        # or use a local model
        hash_val = hash(text.lower().strip())
        # Generate a 384-dimensional vector (typical for embedding models)
        vector = []
        for i in range(384):
            # Use deterministic pseudo-random based on hash and position
            val = ((hash_val * (i + 1)) % 1000) / 1000.0
            vector.append(val * 2 - 1)  # Range [-1, 1]
        return vector

    def _load_embeddings_for_document(self, document_id):
        """Load all chunk embeddings for a document"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT dc.id, dc.chunk_index, dc.chunk_text, de.embedding_vector
            FROM document_chunks dc
            LEFT JOIN document_embeddings de ON dc.id = de.chunk_id
            WHERE dc.document_id = ?
            ORDER BY dc.chunk_index
        ''', (document_id,))

        chunks = []
        for row in cursor.fetchall():
            chunk_id, chunk_index, chunk_text, embedding_json = row
            embedding = None
            if embedding_json:
                try:
                    embedding = json.loads(embedding_json)
                except:
                    embedding = self._get_embedding(chunk_text)  # Fallback
            else:
                embedding = self._get_embedding(chunk_text)  # Generate if missing

            chunks.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "chunk_text": chunk_text,
                "embedding_vector": embedding
            })

        conn.close()
        return chunks

    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == "/health":
            self._handle_health()
        else:
            self._handle_not_found()

    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""

        if path == "/retrieve":
            self._handle_retrieve(post_data)
        elif path == "/embed":
            self._handle_embed(post_data)
        else:
            self._handle_not_found()

    def _handle_health(self):
        """Health check endpoint"""
        doc_count = 0
        chunk_count = 0
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM documents")
            doc_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            chunk_count = cursor.fetchone()[0]
            conn.close()
        except:
            pass

        self._send_json_response({
            "status": "healthy",
            "service": "Shared Local RAG Server",
            "version": "1.0.0",
            "database_path": self.db_path,
            "documents": doc_count,
            "chunks": chunk_count
        })

    def _handle_retrieve(self, post_data):
        """Retrieve relevant document chunks for a query"""
        try:
            data = json.loads(post_data) if post_data else {}
            query = data.get('query', '').strip()
            top_k = int(data.get('top_k', self.DEFAULT_TOP_K))

            if not query:
                self._send_json_response({
                    "error": "Query is required",
                    "results": [],
                    "plan": {"phase": "plan", "description": "No query provided"},
                    "act": {"phase": "act", "description": "No query to embed"},
                    "observe": {"phase": "observe", "description": "No results to observe"}
                }, status_code=400)
                return

            # Plan phase
            plan_result = {
                "phase": "plan",
                "description": f"Read search query and plan to retrieve top {top_k} relevant chunks",
                "query": query,
                "top_k": top_k
            }

            # Act phase: embed query and score against stored chunks
            query_vector = self._get_embedding(query)
            act_result = self._score_chunks_against_query(query_vector)
            act_result.update({
                "phase": "act",
                "description": f"Embedded query and computed cosine similarity with {len(act_result.get('scored_chunks', []))} chunks",
                "model_name": "local-hash-embedding-demo"
            })

            # Observe phase: rank and select top_k
            observe_result = self._rank_and_select_top_k(act_result, top_k)
            observe_result.update({
                "phase": "observe",
                "description": f"Ranked {len(act_result.get('scored_chunks', []))} chunks and selected top {observe_result.get('result_count', 0)}"
            })

            # Format results for response
            results = []
            for chunk in observe_result.get("results", []):
                results.append({
                    "document_id": chunk["document_id"],
                    "title": chunk.get("title", "Unknown"),
                    "source": chunk.get("source", "Unknown"),
                    "doc_type": chunk.get("doc_type", "unknown"),
                    "published_on": chunk.get("published_on", ""),
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"],
                    "score": round(chunk["score"], 4)
                })

            self._send_json_response({
                "query": query,
                "plan": plan_result,
                "act": act_result,
                "observe": observe_result,
                "results": results
            })

        except json.JSONDecodeError:
            self._send_json_response({
                "error": "Invalid JSON",
                "results": []
            }, status_code=400)
        except Exception as e:
            self._send_json_response({
                "error": str(e),
                "results": []
            }, status_code=500)

    def _handle_embed(self, post_data):
        """Embed text using local embedding function"""
        try:
            data = json.loads(post_data) if post_data else {}
            text = data.get('text', '').strip()

            if not text:
                self._send_json_response({
                    "error": "Text is required",
                    "vector": [],
                    "model": "local-hash-embedding-demo"
                }, status_code=400)
                return

            vector = self._get_embedding(text)
            self._send_json_response({
                "text": text,
                "vector": vector,
                "model": "local-hash-embedding-demo",
                "dimensions": len(vector)
            })

        except json.JSONDecodeError:
            self._send_json_response({
                "error": "Invalid JSON",
                "vector": [],
                "model": "local-hash-embedding-demo"
            }, status_code=400)
        except Exception as e:
            self._send_json_response({
                "error": str(e),
                "vector": [],
                "model": "local-hash-embedding-demo"
            }, status_code=500)

    def _score_chunks_against_query(self, query_vector):
        """Score all document chunks against the query vector"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all documents with their chunks
        cursor.execute('''
            SELECT d.id, d.title, d.source, d.doc_type, d.published_on,
                   dc.id, dc.chunk_index, dc.chunk_text, de.embedding_vector
            FROM documents d
            JOIN document_chunks dc ON d.id = dc.document_id
            LEFT JOIN document_embeddings de ON dc.id = de.chunk_id
            ORDER BY d.id, dc.chunk_index
        ''')

        scored_chunks = []
        for row in cursor.fetchall():
            (doc_id, title, source, doc_type, published_on,
             chunk_id, chunk_index, chunk_text, embedding_json) = row

            # Get or compute embedding vector
            if embedding_json:
                try:
                    chunk_vector = json.loads(embedding_json)
                except:
                    chunk_vector = self._get_embedding(chunk_text)
            else:
                chunk_vector = self._get_embedding(chunk_text)

            # Compute cosine similarity
            score = self._cosine_similarity(query_vector, chunk_vector)

            scored_chunks.append({
                "document_id": doc_id,
                "title": title,
                "source": source,
                "doc_type": doc_type,
                "published_on": published_on,
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "chunk_text": chunk_text,
                "score": score,
                "embedding_vector": chunk_vector  # Include for debugging if needed
            })

        conn.close()

        return {
            "scored_chunks": scored_chunks,
            "query_vector": query_vector
        }

    def _rank_and_select_top_k(self, act_result, top_k):
        """Rank chunks by score and select top_k"""
        scored_chunks = act_result.get("scored_chunks", [])

        # Filter out chunks with scores below minimum threshold
        filtered_chunks = [
            chunk for chunk in scored_chunks
            if chunk["score"] > self.MIN_SIMILARITY_SCORE
        ]

        # Sort by score descending
        ranked_chunks = sorted(filtered_chunks, key=lambda x: x["score"], reverse=True)

        # Select top_k
        top_chunks = ranked_chunks[:top_k]

        # Format results for observe phase (without embedding vectors to keep response clean)
        results = []
        for chunk in top_chunks:
            # Get document info for each chunk
            chunk_result = {
                "document_id": chunk["document_id"],
                "title": chunk["title"],
                "source": chunk["source"],
                "doc_type": chunk["doc_type"],
                "published_on": chunk["published_on"],
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"],
                "score": round(chunk["score"], 4)
            }
            results.append(chunk_result)

        return {
            "results": results,
            "result_count": len(results),
            "all_scanned": len(scored_chunks),
            "filtered_count": len(filtered_chunks)
        }

    def _handle_not_found(self):
        """Handle 404 Not Found"""
        self._send_json_response({
            "error": "Endpoint not found",
            "available_endpoints": [
                "GET /health",
                "POST /retrieve",
                "POST /embed"
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


def run_server(port=8091):
    """Run the RAG server on specified port"""
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, RAGHandler)
    print(f"Shared Local RAG Server running on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down RAG server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()