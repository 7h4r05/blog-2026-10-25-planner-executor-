
import json
from typing import Any

from agents.base import BaseAgent
from core.logger import log


class CodeExecutor(BaseAgent):
    name = "code_executor"
    tool_name = "generate_terraform"
    description = (
        "Generate Terraform HCL for one resource from the user's request. "
        "Plan check_state for the same resource first."
    )

    SYSTEM_PROMPT = """
You are a Terraform HCL code generator specializing in Microsoft Azure.

Generate Terraform configuration for the resource described by the step,
in the context of the user's infrastructure request.

Return ONLY valid JSON with this structure:
{
  "hcl": "Terraform HCL configuration here",
  "assumptions": []
}

Rules:
- The hcl field must contain Terraform configuration, not JSON.
- Return HCL as a JSON string inside the hcl field.
- Do not return file paths, filenames, or a files array.
- Do not write files or claim to have written files.
- Do not claim that infrastructure has been deployed.
- Never invent existing resource IDs or state lookup results.
- existing_resources are already managed by Terraform: reference them
  (for example their resource group) instead of defining them again.
- Map Azure service names to their correct AzureRM resource types.
- Use Terraform data sources when appropriate.
- Include required variables and outputs where appropriate.
- Clearly identify assumptions and unresolved configuration values.
- Never execute terraform apply.
- Use valid Terraform HCL syntax.
- Keep explanatory prose outside the hcl field.
"""

    def run(self, task):
        user_prompt = json.dumps(
            {
                "request": task["request"],
                "step": task.get("step", {}),
                "existing_resources": task.get("existing_resources", []),
            },
            ensure_ascii=False,
        )

        response = self.llm.chat(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format_json=True,
        )
        data = json.loads(response)

        hcl = data.get("hcl")
        if not isinstance(hcl, str) or not hcl.strip():
            raise ValueError("The model returned no Terraform HCL.")

        assumptions = data.get("assumptions", [])
        if not isinstance(assumptions, list):
            raise ValueError("'assumptions' must be a list.")

        log("Code executor finished")
        return {
            "status": "code_generated",
            "hcl": hcl,
            "assumptions": assumptions,
            "message": "Terraform HCL was generated.",
        }

    def run_node(self, state: dict[str, Any]) -> dict[str, Any]:
        log("Node executed: ", {"node": self.name})
        history = state.get("history", [])
        step = state.get("current_step") or {}
        parameters = {
            "resourceType": step.get("resourceType"),
            "resourceName": step.get("resourceName"),
            "location": step.get("location"),
        }

        # Resources found by state checks (e.g. a resource group) can be
        # referenced by the generated configuration instead of being redefined.
        existing_resources = [
            resource
            for item in history
            if item.get("action") == "check_state"
            and item.get("status") == "success"
            for resource in item["output"]["results"]
        ]

        try:
            result = {
                "status": "success",
                "output": self.run(
                    {
                        "request": state["user_request"],
                        "step": parameters,
                        "existing_resources": existing_resources,
                    }
                ),
            }
        except Exception as exc:
            result = {
                "status": "error",
                "message": f"Terraform code generation failed: {exc}",
            }

        result = {
            "action": self.tool_name,
            "parameters": parameters,
            "reason": step.get("reason"),
            **result,
        }
        return {"history": history + [result]}
