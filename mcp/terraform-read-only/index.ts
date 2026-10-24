import { McpServer } from "@modelcontextprotocol/server";
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import * as z from "zod/v4";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TerraformService } from "./terraform.service.js";
import type { TerraformModule, TerraformResource } from "./types.js";
import dotenv from 'dotenv';
import { log } from "./logger.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);


dotenv.config({
  path: path.join(__dirname, '.env'),
});


const { TERRAFORM_WORKING_DIR, TERRAFORM_BIN } = process.env;

if (!TERRAFORM_WORKING_DIR || !TERRAFORM_BIN) {
  throw new Error(
    "Set TERRAFORM_WORKING_DIR and TERRAFORM_BIN in mcp/terraform-read-only/.env"
  );
}

const terraform = new TerraformService(TERRAFORM_WORKING_DIR, TERRAFORM_BIN);

const server = new McpServer({
  name: "terraform-read-only-mcp",
  version: "1.0.0"
});

server.registerTool(
  "terraform_search_state",
  {
    description:
      "Searches the current Terraform state for resources matching " +
      "the optional resource type, name, and Azure location. " +
      "Type filter must match, name or location can be a subset. Searches nested modules too.",
    inputSchema: z.object({
      resourceType: z.string().optional().describe(
        "Terraform resource type, e.g. azurerm_linux_virtual_machine"
      ),
      resourceName: z.string().optional().describe(
        "Terraform or Azure resource name, e.g. web_server"
      ),
      location: z.string().optional().describe(
        "Azure location, e.g. westeurope"
      )
    })
  },
  async ({ resourceType, resourceName, location }) => {
    try {
      log("Searching Terraform state", {
        resourceType,
        resourceName,
        location
      });
      const state = await terraform.getState();
      log('State received');

      const rootModule = state.values?.root_module;

      if (!rootModule) {
        throw new Error(
          "Invalid Terraform state JSON: root_module not found"
        );
      }

      const resources: TerraformResource[] = [];

      const collectResources = (module: TerraformModule): void => {
        resources.push(...(module.resources ?? []));

        for (const child of module.child_modules ?? []) {
          collectResources(child);
        }
      };

      collectResources(rootModule);

      // Azure regions appear as "westeurope" in state and "West Europe" in prompts.
      const normalize = (value: string) =>
        value.toLowerCase().replace(/[\s_-]/g, "");

      const matches = resources.filter((resource) => {
        if (
          resourceType &&
          resource.type?.toLowerCase() !== resourceType.toLowerCase()
        ) {
          return false;
        }

        if (resourceName) {
          // Match the Terraform address name and the Azure resource name.
          const azureName = resource.values?.name;
          const names = [
            resource.name,
            typeof azureName === "string" ? azureName : ""
          ];

          if (
            !names.some((name) =>
              normalize(name).includes(normalize(resourceName))
            )
          ) {
            return false;
          }
        }

        if (location) {
          const resourceLocation = resource.values?.location;

          if (
            typeof resourceLocation !== "string" ||
            !normalize(resourceLocation).includes(normalize(location))
          ) {
            return false;
          }
        }

        return true;
      });

      if (matches.length === 0) {
        log("No matching Terraform resource found");

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({
                exists: false,
                results: []
              })
            }
          ]
        };
      }

      const result = {
        exists: true,
        results: matches.map((match) => {
          const matchValues = match.values ?? {};
          return {
            resource_id: typeof matchValues.id === "string" ? matchValues.id : null,
            resource_name:
              typeof matchValues.name === "string"
                ? matchValues.name
                : null,
            resource_type: typeof match.type === "string"
              ? match.type
              : null,
            resource_group:
              typeof matchValues.resource_group_name === "string"
                ? matchValues.resource_group_name
                : null,
            location: typeof matchValues.location === "string" ? matchValues.location : null
          };
        })
      };

      log("Matching Terraform resources found", result?.results?.length);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(result)
          }
        ]
      };
    } catch (error) {
      log("Failed to search Terraform state", error);

      return {
        isError: true,
        content: [
          {
            type: "text" as const,
            text: `Failed to search Terraform state: ${
              error instanceof Error
                ? error.message
                : String(error)
            }`
          }
        ]
      };
    }
  }
);

log(
  "Terraform MCP server started"
);
await serveStdio(() => server);
