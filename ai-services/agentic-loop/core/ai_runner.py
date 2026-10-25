import os
import json
import requests


class AIRunner:
    def __init__(self):
        self.base_url = os.getenv(
            "OLLAMA_URL",
            "http://localhost:11434"
        )

        self.model = os.getenv(
            "OLLAMA_MODEL",
            "qwen2.5:7b"
        )

    def run(self, prompt: str) -> str:
        print(f"Model: {self.model}")
        print(f"Prompt size: {len(prompt):,} characters")

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "num_predict": 2500,
                        "num_ctx": 16384,
                        "temperature": 0,
                    },
                },
                stream=True,
                timeout=(10, 600),
            )

            response.raise_for_status()

            full_response = ""
            final_chunk = {}

            print("\nAI response:\n")

            for line in response.iter_lines():
                if not line:
                    continue

                chunk = json.loads(line.decode("utf-8"))

                text = chunk.get("response", "")

                if text:
                    print(text, end="", flush=True)
                    full_response += text

                if chunk.get("done"):
                    final_chunk = chunk

            print()

            if final_chunk.get("done_reason") == "length":
                print(
                    "\nWARNING: Response reached the "
                    "generation token limit."
                )

            print(
                "Prompt tokens:",
                final_chunk.get("prompt_eval_count", "unknown")
            )

            print(
                "Generated tokens:",
                final_chunk.get("eval_count", "unknown")
            )

            return full_response

        except requests.exceptions.Timeout:
            return (
                "REVIEW ERROR: Ollama timed out. "
                "Reduce the amount of repository evidence."
            )

        except requests.exceptions.ConnectionError:
            return "REVIEW ERROR: Could not connect to Ollama."

        except Exception as error:
            return f"REVIEW ERROR: {error}"