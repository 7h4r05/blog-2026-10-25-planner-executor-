// Subset of the `terraform show -json` output used by the search tool.
export interface TerraformState {
  format_version?: string;
  terraform_version?: string;
  values?: {
    root_module?: TerraformModule;
  };
}

export interface TerraformModule {
  resources?: TerraformResource[];
  child_modules?: TerraformModule[];
}

export interface TerraformResource {
  address: string;
  type: string;
  name: string;
  values?: Record<string, unknown>;
}
