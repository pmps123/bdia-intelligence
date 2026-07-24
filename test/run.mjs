import { createJiti } from "jiti";
import { resolve } from "node:path";

const target = process.argv[2];
if (!target) {
  console.error("Usage: node test/run.mjs <path/to/script.ts>");
  process.exit(1);
}
const jiti = createJiti(import.meta.url, {
  alias: { "@": resolve(process.cwd(), "src") },
});
await jiti.import(resolve(process.cwd(), target));
