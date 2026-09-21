import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
export const openapiPath = resolve(here, "../../examples/openapi.v1.json");
export const openapiOutputPath = resolve(here, "../src/api/openapi.generated.ts");

export async function renderOpenApiContracts() {
  await readFile(openapiPath, "utf8");
  const nodes = await openapiTS(pathToFileURL(openapiPath));
  return astToString(nodes);
}
