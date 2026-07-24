/**
 * Real-document checks for the text-layer PDF reconstruction pipeline (src/lib/parse/pdf-text-layer.ts).
 * Run: node test/run.mjs test/pdf-text-layer-check.ts
 */
import * as assert from "assert";
import { readFileSync } from "fs";
import { extractPositionedItems } from "../src/lib/parse/pdf-text-layer";

async function checkExtractPositionedItems() {
  const buf = readFileSync("Data Vendor/Panasonic Pump.pdf");
  const pages = await extractPositionedItems(buf);
  assert.strictEqual(pages.length, 1, `expected 1 page, got ${pages.length}`);
  const items = pages[0];
  assert.ok(items.length > 50, `expected >50 text items on the page, got ${items.length}`);

  const noItem = items.find((w) => w.text === "No");
  assert.ok(noItem, `expected an item with text "No"`);
  assert.ok(Math.abs(noItem!.x0 - 130.6) < 2, `"No" x0 expected ~130.6, got ${noItem!.x0}`);
  assert.ok(Math.abs(noItem!.y0 - 620.2) < 2, `"No" y0 expected ~620.2, got ${noItem!.y0}`);

  const productItem = items.find((w) => w.text === "Product");
  assert.ok(productItem, `expected an item with text "Product"`);

  const codeItem = items.find((w) => w.text === "GA-126JAK-P");
  assert.ok(codeItem, `expected an item with text "GA-126JAK-P" (a real product type code)`);

  console.log("checkExtractPositionedItems OK");
}

checkExtractPositionedItems().catch((e) => {
  console.error(e);
  process.exit(1);
});
