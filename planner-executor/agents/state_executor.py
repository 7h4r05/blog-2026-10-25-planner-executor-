
from typing import Any

from agents.base import BaseAgent
from core.logger import log


class StateExecutor(BaseAgent):
    name = "state_executor"
    tool_name = "check_state"
    description = (
        "Search Terraform state for a resource using optional "
        "type, name, and location filters."
    )

    def __init__(self, llm=None, mcp_client=None):
        super().__init__(llm=llm)
        self.mcp_client = mcp_client

    def run(self, task):
        payload = self.mcp_client.search_state(
            resource_type=task.get("resourceType"),
            resource_name=task.get("resourceName"),
            location=task.get("location"),
        )

        exists = payload.get("exists")
        results = payload.get("results")

        if not isinstance(exists, bool):
            raise ValueError("Missing or invalid 'exists' field.")
        if not isinstance(results, list):
            raise ValueError("Missing or invalid 'results' field.")
        if exists and not results:
            raise ValueError("MCP reported exists=true but returned no results.")

        log("State executor finished")
        return {
            "status": "found" if exists else "not_found",
            "exists": exists,
            "results": [
                {
                    "resource_id": item.get("resource_id"),
                    "resource_name": item.get("resource_name"),
                    "resource_type": item.get("resource_type"),
                    "resource_group": item.get("resource_group"),
                    "location": item.get("location"),
                }
                for item in results
            ],
            "message": (
                "Matching resources were found."
                if exists
                else "No matching resources were found in Terraform state."
            ),
        }

    def run_node(self, state: dict[str, Any]) -> dict[str, Any]:
        log("Node executed: ", {"node": self.name})
        step = state.get("current_step") or {}
        parameters = {
            "resourceType": step.get("resourceType"),
            "resourceName": step.get("resourceName"),
            "location": step.get("location"),
        }

        try:
            result = {
                "status": "success",
                "output": self.run(parameters),
            }
        except Exception as exc:
            result = {
                "status": "error",
                "message": f"Terraform state search failed: {exc}",
            }

        result = {
            "action": self.tool_name,
            "parameters": parameters,
            "reason": step.get("reason"),
            **result,
        }
        return {"history": state.get("history", []) + [result]}
