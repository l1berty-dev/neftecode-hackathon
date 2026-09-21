import { writeFile } from "node:fs/promises";
import { outputPath, renderContracts } from "./contract-codegen.mjs";
import { openapiOutputPath, renderOpenApiContracts } from "./openapi-codegen.mjs";

const [domainContracts, transportContracts] = await Promise.all([
  renderContracts(),
  renderOpenApiContracts(),
]);
await Promise.all([
  writeFile(outputPath, domainContracts, "utf8"),
  writeFile(openapiOutputPath, transportContracts, "utf8"),
]);
