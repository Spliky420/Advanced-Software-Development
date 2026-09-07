import os
import requests


class AIRunner:
    def __init__(self):
        self.base_url = os.getenv(
            "OLLAMA_URL",
            "http://localhost:11434"
        )

        self.model = os.getenv(
            "OLLAMA_MODEL",
            "qwen2.5:0.5b"
        )

    def run(self, prompt: str) -> str:
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            },
            timeout=300
        )

        response.raise_for_status()

        data = response.json()

        return data["response"]