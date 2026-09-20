import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../examples/contract_v1.schema.json");
const outputPath = resolve(here, "../src/api/contracts.generated.ts");
const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const generated = await compile(schema, "ContractExample", {
  bannerComment:
    "/* AUTO-GENERATED from examples/contract_v1.schema.json. Do not edit manually. */",
  additionalProperties: false,
  style: { singleQuote: false, semi: true, tabWidth: 2 },
});

await writeFile(outputPath, generated, "utf8");
