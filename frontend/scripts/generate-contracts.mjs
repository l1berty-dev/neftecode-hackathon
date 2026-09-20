import { writeFile } from "node:fs/promises";
import { outputPath, renderContracts } from "./contract-codegen.mjs";

await writeFile(outputPath, await renderContracts(), "utf8");
