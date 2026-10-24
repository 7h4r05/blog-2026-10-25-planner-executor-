import json
from typing import Any

from agents.base import BaseAgent
from core.history import found_resources, generated_hcl, without_hcl
from core.logger import log


class ResponseAgent(BaseAgent):
    """Uses an LLM to explain verified workflow outcomes."""

    name = "response_executor"
    description = "Explains the final infrastructure workflow result."

    SYSTEM_PROMPT = """
You are the response agent for an Azure Terraform assistant.

Write a concise, clear response.

Use only facts contained in the supplied user request and workflow result.
Do not claim a resource exists in Azure based only on Terraform state.
If the workflow result contains an error, report that error accurately and do
not invent its cause or suggest unrelated troubleshooting steps.
Terraform configuration generation does not mean it was applied or deployed.
Generated HCL is not included in the workflow result; it is appended below
your response automatically. Do not write HCL yourself.
Resources found in Terraform state, with their IDs, are also listed below
your response automatically. Do not repeat resource IDs yourself.
Do not recommend terraform apply.
"""

    def run(self, task):
        if not isinstance(task, dict):
            raise TypeError("ResponseAgent expects task to be a dictionary.")

        workflow_result = task.get("workflow_result")
        if not isinstance(workflow_result, dict):
            raise ValueError("Task must contain a dictionary 'workflow_result'.")

        messages = [
            {
                "role": "system",
                "content": self.SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": task.get("user_request", ""),
                        "workflow_result": workflow_result,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

        response = self.llm.chat(messages)
        if not isinstance(response, str) or not response.strip():
            raise ValueError("The response model returned an empty response.")

        return response.strip()

    def run_node(self, state: dict[str, Any]) -> dict[str, Any]:
        log("Node executed: ", {"node": self.name})
        history = state.get("history", [])
        workflow_result = {
            "status": (
                "error"
                if state.get("error")
                or any(item.get("status") == "error" for item in history)
                else "completed"
            ),
            "plan": state.get("initial_plan", []),
            "results": without_hcl(history),
            "error": state.get("error"),
        }

        try:
            response = self.run(
                {
                    "user_request": state["user_request"],
                    "workflow_result": workflow_result,
                }
            )
        except Exception as exc:
            response = json.dumps(
                workflow_result,
                ensure_ascii=False,
                indent=2,
            )
            response += f"\nResponse generation failed: {exc}"

        # Facts go to the user verbatim; a small model could drop or alter them.
        resources = found_resources(history)
        if resources:
            response += "\n\nResources found in Terraform state:"
            for resource in resources:
                response += _format_resource(resource)

        for hcl in generated_hcl(history):
            response += f"\n\n```hcl\n{hcl.strip()}\n```"

        return {"response": str(response)}


def _format_resource(resource: dict[str, Any]) -> str:
    def value(key):
        return resource.get(key) or "unknown"

    return (
        f"\n- {value('resource_name')} ({value('resource_type')}), "
        f"resource group: {value('resource_group')}, "
        f"location: {value('location')}"
        f"\n  id: {value('resource_id')}"
    )
