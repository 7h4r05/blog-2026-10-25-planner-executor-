import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import OLLAMA_NUM_CTX, REQUEST_TIMEOUT


class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(
        self,
        messages: list[dict],
        format_json: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        }

        # A JSON schema constrains the output (Ollama structured outputs).
        if schema:
            payload["format"] = schema
        elif format_json:
            payload["format"] = "json"

        data = self.__chat_request(payload)
        try:
            return data["message"]["content"].strip()
        except (AttributeError, KeyError) as exc:
            raise RuntimeError(
                "Ollama returned an invalid response."
            ) from exc

    def __chat_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json"
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=REQUEST_TIMEOUT
            ) as response:
                data = json.loads(
                    response.read().decode("utf-8")
                )

            if not isinstance(data, dict):
                raise ValueError("Ollama returned an invalid chat response.")

            return data

        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace"
            )
            if exc.code == 404:
                raise RuntimeError(
                    f"Model {self.model} was not found. "
                    f"Run: ollama pull {self.model}"
                ) from exc

            raise RuntimeError(
                f"Ollama HTTP error ({exc.code}): {detail}"
            ) from exc

        except URLError as exc:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Check that Ollama is running."
            ) from exc

        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out while waiting for Ollama."
            ) from exc

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Ollama returned an invalid response."
            ) from exc
