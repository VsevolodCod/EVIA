import { expect, it } from "vitest";
import { readFileSync } from "node:fs";

const styles = readFileSync("src/styles.css", "utf8");

it("keeps desktop workspace panels inside the viewport with independent scrolling", () => {
  expect(styles).toMatch(/@media \(min-width: 1001px\)[\s\S]*?\.workspace\s*\{[\s\S]*?height:\s*calc\(100dvh - 72px\)/);
  expect(styles).toMatch(/@media \(min-width: 1001px\)[\s\S]*?\.sidebar,[\s\S]*?\.analysis\s*\{[\s\S]*?overflow-y:\s*auto/);
  expect(styles).toMatch(/@media \(min-width: 1001px\)[\s\S]*?\.chat-content\s*\{[\s\S]*?overflow-y:\s*auto/);
});
