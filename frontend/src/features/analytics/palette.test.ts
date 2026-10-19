import { describe, expect, it } from "vitest";
import {
  defaultPalette,
  loadPalette,
  parsePalette,
  savePalette,
  seriesColor,
  validatePalette,
} from "./palette";

describe("palette", () => {
  it("accepts JSON and comma-separated hex colors", () => {
    expect(parsePalette('["#518ed5", "#DDAA65"]')).toEqual(["#518ed5", "#ddaa65"]);
    expect(parsePalette("#518ed5, #ddaa65 #8873bb")).toEqual([
      "#518ed5", "#ddaa65", "#8873bb",
    ]);
  });

  it("rejects incomplete palettes and non-hex input", () => {
    expect(() => validatePalette(["#518ed5"])).toThrow("от 2 до 12");
    expect(() => parsePalette("red, url(javascript:alert(1))")).toThrow("#RRGGBB");
  });

  it("assigns a stable color to a series key without depending on order", () => {
    const palette = defaultPalette.colors;
    expect(seriesColor("Подписчики", palette)).toBe(seriesColor("Подписчики", palette));
    expect(seriesColor("Без подписки", palette)).not.toBeUndefined();
  });

  it("keeps gradient preference scoped to the selected source", () => {
    savePalette("first", { colors: ["#112233", "#445566"], gradient: true });
    savePalette("second", { colors: ["#778899", "#aabbcc"], gradient: false });
    expect(loadPalette("first")).toEqual({ colors: ["#112233", "#445566"], gradient: true });
    expect(loadPalette("second")).toEqual({ colors: ["#778899", "#aabbcc"], gradient: false });
  });
});
