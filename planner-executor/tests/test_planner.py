"""Planner rules tested with a scripted LLM and an in-memory Terraform state.

Run from planner-executor/: python -m unittest discover tests
"""

import json
import unittest
from unittest.mock import patch

import core.manager
from agents.planner import PlannerAgent

COSMOS = "azurerm_cosmosdb_account"
HCL = 'resource "azurerm_cosmosdb_account" "db" {}'


def step(action, resource_name=None, resource_type=COSMOS, location=None):
    return {
        "action": action,
        "resourceType": resource_type,
        "resourceName": resource_name,
        "location": location,
        "reason": "test",
    }


class FakeMCP:
    def __init__(self, managed_names):
        self.managed_names = managed_names

    def search_state(self, resource_type=None, resource_name=None, location=None):
        matches = [
            name for name in self.managed_names
            if resource_name is None or resource_name in name
        ]
        return {
            "exists": bool(matches),
            "results": [
                {
                    "resource_id": f"/subscriptions/test/{name}",
                    "resource_name": name,
                    "resource_type": resource_type,
                }
                for name in matches
            ],
        }


class FakeLLM:
    """Returns scripted plans and records what each call received."""

    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = []
        self.replan_inputs = []

    def chat(self, messages, format_json=False, schema=None):
        system, user = messages[0]["content"], messages[1]["content"]
        if schema:
            kind = "replan" if "replanner" in system else "plan"
            self.calls.append(kind)
            if kind == "replan":
                self.replan_inputs.append(user)
            return json.dumps({"steps": self.plans.pop(0)})
        if format_json:
            self.calls.append("code")
            return json.dumps({"hcl": HCL, "assumptions": []})
        self.calls.append("respond")
        return "summary"


def run_workflow(plans, managed_names=()):
    llm = FakeLLM(plans)
    with patch.object(
        core.manager, "TerraformMCPClient", lambda: FakeMCP(managed_names)
    ):
        planner = PlannerAgent(llm, core.manager.AgentManager(llm))
    captured = {}
    responder_run = planner.responder.run

    def capture(task):
        captured.update(task["workflow_result"])
        return responder_run(task)

    planner.responder.run = capture
    response = planner.run("create a Cosmos DB account")
    return llm, captured, response


def executed(result):
    return [(item["action"], item["status"]) for item in result["results"]]


class PlannerRulesTest(unittest.TestCase):
    def test_missing_state_check_is_inserted(self):
        llm, result, _ = run_workflow(
            [
                [step("generate_terraform")],  # model skips the state check
                [step("generate_terraform")],
            ]
        )

        self.assertEqual(
            [s["action"] for s in result["plan"]],
            ["check_state", "generate_terraform"],
        )
        self.assertEqual(
            executed(result),
            [("check_state", "success"), ("generate_terraform", "success")],
        )

    def test_vague_state_check_is_replaced_by_exact_one(self):
        # Seen with qwen2.5:7b: a location-only check before a typed generation.
        llm, result, _ = run_workflow(
            [
                [
                    step("check_state", resource_type=None, location="polandcentral"),
                    step("generate_terraform", location="polandcentral"),
                ],
                [step("generate_terraform", location="polandcentral")],
            ]
        )

        self.assertEqual(
            result["plan"],
            [
                {**step("check_state", location="polandcentral"),
                 "reason": "Check Terraform state before generating configuration."},
                step("generate_terraform", location="polandcentral"),
            ],
        )

    def test_generation_dropped_when_resource_is_in_state(self):
        llm, result, _ = run_workflow(
            [
                [step("check_state"), step("generate_terraform")],
                [step("generate_terraform")],  # model ignores the state result
            ],
            managed_names=["prod-db"],
        )

        self.assertEqual(executed(result), [("check_state", "success")])
        self.assertNotIn("code", llm.calls)

    def test_found_resource_id_reaches_user(self):
        _, _, response = run_workflow(
            [[step("check_state")], []],
            managed_names=["prod-db"],
        )

        self.assertIn("id: /subscriptions/test/prod-db", response)

    def test_other_resource_of_same_type_does_not_block_generation(self):
        llm, result, _ = run_workflow(
            [
                [step("check_state", "logs-db"), step("generate_terraform", "logs-db")],
                [step("generate_terraform", "logs-db")],
            ],
            managed_names=["prod-db"],
        )

        self.assertEqual(
            executed(result),
            [("check_state", "success"), ("generate_terraform", "success")],
        )

    def test_repeated_steps_are_dropped(self):
        llm, result, _ = run_workflow(
            [
                [step("check_state"), step("generate_terraform")],
                [step("check_state"), step("generate_terraform")],
            ]
        )

        self.assertEqual(
            executed(result),
            [("check_state", "success"), ("generate_terraform", "success")],
        )

    def test_no_replan_after_final_generation(self):
        llm, _, _ = run_workflow(
            [
                [step("check_state"), step("generate_terraform")],
                [step("generate_terraform")],
            ]
        )

        self.assertEqual(llm.calls, ["plan", "replan", "code", "respond"])

    def test_hcl_bypasses_llm_prompts_and_reaches_user(self):
        llm, result, response = run_workflow(
            [
                [step("generate_terraform")],
                [step("generate_terraform")],
            ]
        )

        self.assertNotIn(HCL, json.dumps(result))
        self.assertTrue(all(HCL not in text for text in llm.replan_inputs))
        self.assertIn(f"```hcl\n{HCL}\n```", response)


if __name__ == "__main__":
    unittest.main()
