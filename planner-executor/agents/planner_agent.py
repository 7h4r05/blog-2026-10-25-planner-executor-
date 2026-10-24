
import json
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from agents.base import BaseAgent
from core.config import MAX_PLAN_STEPS
from core.history import without_hcl
from core.logger import log


FILTER_FIELDS = ("resourceType", "resourceName", "location")


class WorkflowState(TypedDict, total=False):
    user_request: str
    initial_plan: list[dict[str, Any]]
    plan: list[dict[str, Any]]  # steps still waiting for execution
    current_step: dict[str, Any] | None  # step handed to an executor
    history: list[dict[str, Any]]  # executed steps with their results
    error: str
    response: str


def _filters(step: dict[str, Any]) -> tuple:
    return tuple(step.get(field) for field in FILTER_FIELDS)


def _is_vaguer(filters: tuple, target: tuple) -> bool:
    """True when filters match target except for fields left as null."""
    return filters != target and all(
        value is None or value == expected
        for value, expected in zip(filters, target)
    )


class PlannerAgent(BaseAgent):
    name = "planner"
    description = (
        "Plans multi-step Azure Terraform tasks and delegates each step "
        "to an executor."
    )

    PLAN_PROMPT = """
You are the planner for an Azure Terraform assistant.

Break the user's request into an ordered list of steps. Every step is run by
a dedicated executor; you never execute anything yourself.

Available actions:
{actions}

Return ONLY valid JSON:
{"steps": [{"action": "...", "resourceType": null, "resourceName": null, "location": null, "reason": "..."}]}

Rules:
- Use at most {max_steps} steps.
- Before generate_terraform for a resource, plan check_state for the same
  resource with exactly the same resourceType, resourceName and location.
- For resourceType, return the exact Terraform AzureRM provider resource type,
  not an Azure display name or ARM type. For example, a Cosmos DB account is
  azurerm_cosmosdb_account, not AzureCosmosDBAccount or
  Microsoft.DocumentDB/databaseAccounts. If the exact Terraform type is
  uncertain, use null rather than inventing a type.
- Use null for unknown resource filters.
- If the request needs no action, return {"steps": []}.
"""

    REPLAN_PROMPT = """
You are the replanner for an Azure Terraform assistant.

You receive the user request, the steps already executed with their results,
and the remaining plan. Return the steps that still need to run, in order.

Available actions:
{actions}

Return ONLY valid JSON:
{"steps": [{"action": "...", "resourceType": null, "resourceName": null, "location": null, "reason": "..."}]}

Rules:
- Never include steps that already succeeded.
- If check_state found the requested resource in Terraform state, do not plan
  generate_terraform for it.
- If check_state did not find it and the user asked for configuration, keep
  generate_terraform for it.
- A resource missing from Terraform state is not proof that it is absent from
  Azure.
- Use exact AzureRM resource types or null, and null for unknown filters.
- If the request is complete, return {"steps": []}.
"""

    def __init__(
        self,
        llm=None,
        manager=None,
    ):
        super().__init__(llm=llm)
        self.manager = manager

        agents = manager.get_agents()
        # Executors register the action they handle through tool_name.
        self.executors = {
            agent.tool_name: agent
            for agent in agents
            if getattr(agent, "tool_name", None)
        }
        self.responder = next(
            agent for agent in agents if agent.name == "response_executor"
        )
        self.graph = self.__build_graph()

    def __system_prompt(self, template: str) -> str:
        actions = "\n".join(
            f"- {action}: {agent.description}"
            for action, agent in self.executors.items()
        )
        return (
            template
            .replace("{actions}", actions)
            .replace("{max_steps}", str(MAX_PLAN_STEPS))
        )

    def __plan_schema(self) -> dict[str, Any]:
        nullable_string = {"type": ["string", "null"]}
        return {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": list(self.executors),
                            },
                            "resourceType": nullable_string,
                            "resourceName": nullable_string,
                            "location": nullable_string,
                            "reason": {"type": "string"},
                        },
                        "required": ["action", *FILTER_FIELDS, "reason"],
                    },
                },
            },
            "required": ["steps"],
        }

    def __ask_for_steps(
        self,
        template: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": self.__system_prompt(template)},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, indent=2),
                },
            ],
            schema=self.__plan_schema(),
        )

        data = json.loads(response)
        steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(steps, list):
            raise ValueError("The model returned no 'steps' list.")

        return [self.__validate_step(step) for step in steps]

    def __validate_step(self, step: Any) -> dict[str, Any]:
        if not isinstance(step, dict):
            raise ValueError("Each plan step must be a JSON object.")

        action = step.get("action")
        if action not in self.executors:
            raise ValueError(f"Unsupported action in plan: {action}")

        normalized = {"action": action}
        for field in FILTER_FIELDS:
            value = step.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"'{field}' must be a string or null.")
            normalized[field] = value or None
        normalized["reason"] = str(step.get("reason") or "")

        return normalized

    def __enforce_rules(
        self,
        steps: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Deterministic plan rules that a small model cannot be trusted with."""
        succeeded = [item for item in history if item.get("status") == "success"]
        done = {
            (item["action"], _filters(item["parameters"]))
            for item in succeeded
        }
        # A resource is identified by all its filters, so an existing storage
        # account does not block generating another one with a different name.
        checked = {
            _filters(item["parameters"])
            for item in succeeded
            if item["action"] == "check_state"
        }
        managed = {
            _filters(item["parameters"])
            for item in succeeded
            if item["action"] == "check_state"
            and item["output"].get("exists") is True
        }

        # A check with fewer filters than the generation it guards, e.g. only a
        # location, matches unrelated resources; the exact check is added below.
        generations = [
            _filters(step) for step in steps
            if step["action"] == "generate_terraform"
        ]
        specific_steps = []
        for step in steps:
            if step["action"] == "check_state" and any(
                _is_vaguer(_filters(step), target) for target in generations
            ):
                log("Planner: dropping vague state check", step)
                continue
            specific_steps.append(step)

        plan = []
        for step in specific_steps:
            key = (step["action"], _filters(step))
            if key in done:
                log("Planner: dropping repeated step", step)
                continue

            if step["action"] == "generate_terraform":
                if _filters(step) in managed:
                    log("Planner: resource already in state, dropping", step)
                    continue
                if _filters(step) not in checked:
                    log("Planner: adding missing state check", step)
                    plan.append(
                        {
                            **step,
                            "action": "check_state",
                            "reason": (
                                "Check Terraform state before generating "
                                "configuration."
                            ),
                        }
                    )
            checked.add(_filters(step))
            plan.append(step)
            done.add(key)

        budget = MAX_PLAN_STEPS - len(history)
        if len(plan) > budget:
            log(f"Planner: trimming plan to the {MAX_PLAN_STEPS}-step limit")
            plan = plan[:max(budget, 0)]

        return plan

    @staticmethod
    def __advance(steps: list[dict[str, Any]]) -> dict[str, Any]:
        if not steps:
            return {"current_step": None, "plan": []}
        return {"current_step": steps[0], "plan": steps[1:]}

    def __build_graph(self):
        def planner_node(state: WorkflowState) -> dict:
            log("Node executed: ", {"node": "planner"})
            try:
                steps = self.__ask_for_steps(
                    self.PLAN_PROMPT,
                    {"user_request": state["user_request"]},
                )
                steps = self.__enforce_rules(steps, [])
            except Exception as exc:
                return {
                    "error": f"Planning failed: {exc}",
                    **self.__advance([]),
                }

            log("Planner: plan created", steps)
            return {"initial_plan": steps, **self.__advance(steps)}

        def replanner_node(state: WorkflowState) -> dict:
            log("Node executed: ", {"node": "replanner"})
            history = state.get("history", [])

            if history and history[-1].get("status") == "error":
                log("Replanner: last step failed, finishing")
                return self.__advance([])

            # Generated code brings no new facts about the infrastructure,
            # so an empty plan after it needs no extra LLM call.
            if not state.get("plan") and history[-1]["action"] == "generate_terraform":
                log("Replanner: plan completed")
                return self.__advance([])

            try:
                steps = self.__ask_for_steps(
                    self.REPLAN_PROMPT,
                    {
                        "user_request": state["user_request"],
                        "executed_steps": without_hcl(history),
                        "remaining_plan": state.get("plan", []),
                    },
                )
                steps = self.__enforce_rules(steps, history)
            except Exception as exc:
                return {
                    "error": f"Replanning failed: {exc}",
                    **self.__advance([]),
                }

            log("Replanner: updated plan", steps)
            return self.__advance(steps)

        def next_node(state: WorkflowState) -> str:
            step = state.get("current_step")
            if not step:
                return self.responder.name
            return self.executors[step["action"]].name

        destinations = [
            *(agent.name for agent in self.executors.values()),
            self.responder.name,
        ]

        graph = StateGraph(WorkflowState)

        graph.add_node("planner", planner_node)
        graph.add_node("replanner", replanner_node)
        for agent in self.manager.get_agents():
            log(f"Adding agent '{agent.name}' to the workflow graph")
            graph.add_node(agent.name, agent.run_node)

        graph.add_edge(START, "planner")
        graph.add_conditional_edges("planner", next_node, destinations)
        for agent in self.executors.values():
            graph.add_edge(agent.name, "replanner")
        graph.add_conditional_edges("replanner", next_node, destinations)
        graph.add_edge(self.responder.name, END)

        return graph.compile()

    def run(self, task):
        log("Planner agent started")

        if isinstance(task, dict):
            user_request = str(task.get("user_request", "")).strip()
        else:
            user_request = str(task).strip()

        if not user_request:
            raise ValueError("The user request cannot be empty.")

        result = self.graph.invoke(
            {
                "user_request": user_request,
                "initial_plan": [],
                "plan": [],
                "current_step": None,
                "history": [],
                "error": "",
            },
            # Each step runs an executor and the replanner.
            config={"recursion_limit": MAX_PLAN_STEPS * 2 + 5},
        )

        log("Planner finished")

        return result.get("response", "Workflow finished without a response.")
