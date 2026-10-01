import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag_pipeline import (
    refresh_corpus,
    retrieve_context,
    answer_question
)


class RAGHandler(BaseHTTPRequestHandler):

    def send_json(self, status, payload):

        data = json.dumps(payload).encode()

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.send_header(
            "Content-Length",
            str(len(data))
        )

        self.end_headers()
        self.wfile.write(data)


    def read_json(self):

        length = int(
            self.headers.get(
                "Content-Length",
                0
            )
        )

        if not length:
            return {}

        return json.loads(
            self.rfile.read(length)
        )


    def do_GET(self):

        if self.path == "/health":

            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "rag-server"
                }
            )

            return

        self.send_json(
            404,
            {"error": "not_found"}
        )


    def do_POST(self):

        try:

            payload = self.read_json()

            if self.path == "/refresh":

                result = refresh_corpus(
                    payload.get(
                        "caller",
                        "student"
                    )
                )

            elif self.path == "/retrieve":

                result = retrieve_context(
                    payload.get("query", ""),
                    int(payload.get("k", 5)),
                    payload.get(
                        "caller",
                        "student"
                    )
                )

            elif self.path == "/answer":

                result = answer_question(
                    payload.get("query", ""),
                    int(payload.get("k", 5)),
                    payload.get(
                        "caller",
                        "student"
                    )
                )

            else:

                self.send_json(
                    404,
                    {"error": "not_found"}
                )

                return

            self.send_json(
                200,
                result
            )

        except Exception as exc:

            self.send_json(
                500,
                {
                    "status": "error",
                    "error": str(exc)
                }
            )


if __name__ == "__main__":

    server = ThreadingHTTPServer(
        ("0.0.0.0", 5003),
        RAGHandler
    )

    print(
        "Personal Finance RAG server "
        "running on http://localhost:5003"
    )

    server.serve_forever()