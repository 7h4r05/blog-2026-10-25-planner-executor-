
from core.ollama_client import OllamaClient
from core.manager import AgentManager
from core.config import OLLAMA_URL, OLLAMA_MODEL
from agents.planner_agent import PlannerAgent
from core.logger import log

def main():
    llm = OllamaClient(
        base_url=OLLAMA_URL,
        model=OLLAMA_MODEL,
    )
    planner = PlannerAgent(llm, AgentManager(llm))

    while True:
        try:
            request = input("\nDescribe the infrastructure request: ").strip()
            if request.lower() in {"exit", "quit"}:
                break

            if not request:
                continue

            result = planner.run(request)
            log("\n" + str(result))

        except KeyboardInterrupt:
            break
        except Exception as exc:
            log(f"Application error: {exc}")


if __name__ == "__main__":
    main()
