export type Palette = {
  id: string;
  label: string;
  colors: string[];
};

export type PalettePreference = {
  colors: string[];
  gradient: boolean;
};

export const palettes: Palette[] = [
  { id: "calm", label: "Спокойная", colors: ["#518ed5", "#ddaa65", "#8873bb", "#679b9a"] },
  { id: "contrast", label: "Контрастная", colors: ["#3166b5", "#c96653", "#7b63a8", "#55846a"] },
  { id: "lavender", label: "Лавандовая", colors: ["#8873bb", "#6b9fb4", "#c78d9a", "#bd9b61"] },
  { id: "marine", label: "Морская", colors: ["#377d97", "#6eafa7", "#b38e62", "#7d80a7"] },
];

export const defaultPalette = palettes[0];
const hex = /^#[a-f\d]{6}$/i;

export function validatePalette(colors: unknown): string[] {
  if (!Array.isArray(colors))
    throw new Error("Палитра должна содержать от 2 до 12 цветов.");
  if (!colors.every((color) => typeof color === "string" && hex.test(color)))
    throw new Error("Используйте цвета в формате #RRGGBB.");
  if (colors.length < 2 || colors.length > 12)
    throw new Error("Палитра должна содержать от 2 до 12 цветов.");
  return colors.map((color) => color.toLowerCase());
}

export function parsePalette(text: string): string[] {
  const value = text.trim();
  if (!value) throw new Error("Добавьте хотя бы два HEX-цвета.");
  try {
    return validatePalette(value.startsWith("[") ? JSON.parse(value) : value.split(/[\s,;]+/).filter(Boolean));
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error("Некорректный JSON с палитрой.");
    throw error;
  }
}

function hash(value: string) {
  return [...value].reduce((result, character) => ((result * 31) + character.charCodeAt(0)) | 0, 0);
}

export function seriesColor(key: string, colors: string[]) {
  return colors[Math.abs(hash(key)) % colors.length];
}

const storageKey = (scope: string) => `evia.dashboard.palette.${scope}`;

export function loadPalette(scope: string): PalettePreference | null {
  try {
    const stored = globalThis.localStorage?.getItem(storageKey(scope));
    if (!stored) return null;
    const value: unknown = JSON.parse(stored);
    if (Array.isArray(value)) return { colors: validatePalette(value), gradient: false };
    if (!value || typeof value !== "object") return null;
    const preference = value as { colors?: unknown; gradient?: unknown };
    if (typeof preference.gradient !== "boolean") return null;
    return { colors: validatePalette(preference.colors), gradient: preference.gradient };
  } catch {
    return null;
  }
}

export function savePalette(scope: string, preference: PalettePreference) {
  try {
    globalThis.localStorage?.setItem(storageKey(scope), JSON.stringify({
      colors: validatePalette(preference.colors),
      gradient: preference.gradient,
    }));
    return true;
  } catch {
    return false;
  }
}
