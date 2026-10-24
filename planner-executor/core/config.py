import os
from pathlib import Path

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen2.5:7b"
)

REQUEST_TIMEOUT = int(
    os.getenv("OLLAMA_TIMEOUT", "180")
)

# Ollama silently truncates prompts longer than the context window.
OLLAMA_NUM_CTX = int(
    os.getenv("OLLAMA_NUM_CTX", "8192")
)

MAX_PLAN_STEPS = int(
    os.getenv("MAX_PLAN_STEPS", "6")
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TERRAFORM_MCP_DIR = (
    PROJECT_ROOT / "../mcp/terraform-read-only"
).resolve()
