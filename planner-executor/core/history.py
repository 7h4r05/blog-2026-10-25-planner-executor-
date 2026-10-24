from typing import Any


def without_hcl(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Step history for LLM prompts.

    Generated HCL is large and the planner and responder only need step
    statuses, so it is left out to keep prompts within the context window.
    """
    return [
        {
            **item,
            "output": {
                key: value
                for key, value in item["output"].items()
                if key != "hcl"
            },
        }
        if isinstance(item.get("output"), dict)
        else item
        for item in history
    ]


def found_resources(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resources returned by successful state checks, without duplicates."""
    resources = {}
    for item in history:
        if item.get("action") == "check_state" and item.get("status") == "success":
            for resource in item["output"]["results"]:
                key = resource.get("resource_id") or resource.get("resource_name")
                resources.setdefault(key, resource)
    return list(resources.values())


def generated_hcl(history: list[dict[str, Any]]) -> list[str]:
    return [
        item["output"]["hcl"]
        for item in history
        if item.get("action") == "generate_terraform"
        and item.get("status") == "success"
    ]
