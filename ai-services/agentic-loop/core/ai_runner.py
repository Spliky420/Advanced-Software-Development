import os
import requests


class AIRunner:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

    def run(self, prompt: str) -> str:
        print(f"Prompt size: {len(prompt):,} characters")

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "num_predict": 220,
                        "num_ctx": 4096,
                        "temperature": 0.1,
                    },
                },
                stream=True,
                timeout=(10, 600),
            )

            response.raise_for_status()

            full_response = ""

            print("AI response:")
            print()

            for line in response.iter_lines():
                if not line:
                    continue

                data = line.decode("utf-8")

                import json

                chunk = json.loads(data)

                text = chunk.get("response", "")

                if text:
                    print(text, end="", flush=True)
                    full_response += text

            print()
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
