import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.config import TERRAFORM_MCP_DIR
from core.logger import log


class TerraformMCPClient:
    async def _search_state(
        self,
        resource_type=None,
        resource_name=None,
        location=None,
    ):
        arguments = {
            key: value
            for key, value in {
                "resourceType": resource_type,
                "resourceName": resource_name,
                "location": location,
            }.items()
            if value is not None
        }

        params = StdioServerParameters(
            command="npx",
            args=["tsx", "index.ts"],
            cwd=str(TERRAFORM_MCP_DIR),
        )

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "terraform_search_state",
                        arguments=arguments,
                    )
                    if result.is_error:
                        error_details = "; ".join(
                            item.text
                            for item in result.content
                            if item.type == "text" and item.text
                        )
                        raise RuntimeError(
                            "Terraform MCP search tool returned an error"
                            + (
                                f": {error_details}"
                                if error_details
                                else "."
                            )
                        )

                    for item in result.content:
                        if item.type == "text":
                            try:
                                payload = json.loads(item.text)
                            except json.JSONDecodeError:
                                log(
                                    "MCP: tool returned invalid JSON."
                                )
                                raise

                            if not isinstance(payload, dict):
                                raise ValueError(
                                    "MCP response must be a JSON object."
                                )

                            log(
                                "MCP: parsed response successfully."
                            )
                            return payload

                    raise ValueError(
                        "Terraform MCP returned no text content."
                    )

        except Exception:
            log("MCP: state search failed.")
            raise

    def search_state(
        self,
        resource_type=None,
        resource_name=None,
        location=None,
    ):
        try:
            result = asyncio.run(
                self._search_state(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    location=location,
                )
            )
            return result

        except Exception:
            log("MCP: search_state raised an exception.")
            raise
