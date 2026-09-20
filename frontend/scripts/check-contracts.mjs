import { readFile } from "node:fs/promises";
import { outputPath, renderContracts, schemaPath } from "./contract-codegen.mjs";

const [expected, actual] = await Promise.all([
  renderContracts(),
  readFile(outputPath, "utf8").catch(() => ""),
]);

if (actual !== expected) {
  const relativeSchema = schemaPath.split("/").slice(-2).join("/");
  throw new Error(
    `Generated contracts are stale relative to ${relativeSchema}. Run npm run generate:contracts.`,
  );
}
