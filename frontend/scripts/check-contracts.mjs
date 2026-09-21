import { readFile } from "node:fs/promises";
import { outputPath, renderContracts, schemaPath } from "./contract-codegen.mjs";
import {
  openapiOutputPath,
  openapiPath,
  renderOpenApiContracts,
} from "./openapi-codegen.mjs";

const [expected, actual, expectedOpenApi, actualOpenApi] = await Promise.all([
  renderContracts(),
  readFile(outputPath, "utf8").catch(() => ""),
  renderOpenApiContracts(),
  readFile(openapiOutputPath, "utf8").catch(() => ""),
]);

if (actual !== expected) {
  const relativeSchema = schemaPath.split("/").slice(-2).join("/");
  throw new Error(
    `Generated contracts are stale relative to ${relativeSchema}. Run npm run generate:contracts.`,
  );
}

if (actualOpenApi !== expectedOpenApi) {
  const relativeOpenApi = openapiPath.split("/").slice(-2).join("/");
  throw new Error(
    `Generated transport types are stale relative to ${relativeOpenApi}. Run npm run generate:contracts.`,
  );
}
