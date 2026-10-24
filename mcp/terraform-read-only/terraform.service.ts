import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

import type {
  TerraformState,
} from "./types.js";


const execFileAsync = promisify(execFile);

export class TerraformService {
  constructor(private readonly workingDirectory: string,
    private readonly terraformPath: string
  ){

  }

  async getState(): Promise<TerraformState> {
    const { stdout } = await execFileAsync(
      this.terraformPath,
      ["show","-json"],
      {
        cwd: path.resolve(this.workingDirectory),
        maxBuffer: 10 * 1024 * 1024
      }
    );

    return JSON.parse(stdout) as TerraformState;
  }
}
