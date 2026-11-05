import { useRef, useState } from "react";
import { useLanguage } from "../../language";
import { palettes, parsePalette } from "./palette";

export function PaletteEditor({
  colors,
  gradient,
  onChange,
  onClose,
}: {
  colors: string[];
  gradient: boolean;
  onChange: (colors: string[], gradient: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useLanguage();
  const [value, setValue] = useState(colors.join(", "));
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const apply = (raw = value) => {
    try {
      const next = parsePalette(raw);
      onChange(next, gradient);
      setValue(next.join(", "));
      setError("");
    } catch (reason) {
      const messages: Record<string, string> = { "Палитра должна содержать от 2 до 12 цветов.": "The palette must contain 2–12 colors.", "Используйте цвета в формате #RRGGBB.": "Use colors in #RRGGBB format.", "Добавьте хотя бы два HEX-цвета.": "Add at least two HEX colors.", "Некорректный JSON с палитрой.": "Invalid palette JSON." };
      setError(reason instanceof Error ? t(reason.message, messages[reason.message] ?? reason.message) : t("Не удалось прочитать палитру.", "Could not read palette."));
    }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    if (file.size > 16 * 1024) {
      setError(t("Файл палитры больше 16 КБ.", "Palette file exceeds 16 KB."));
      return;
    }
    try {
      apply(await file.text());
    } catch {
      setError(t("Не удалось прочитать файл палитры.", "Could not read palette file."));
    }
  };

  return (
    <section className="palette-editor" aria-label={t("Настройка цветов графиков", "Chart color settings")}>
      <div className="palette-editor-heading">
        <strong>{t("Цвета графиков", "Chart colors")}</strong>
        <button className="palette-close" aria-label={t("Закрыть цвета", "Close colors")} onClick={onClose}>×</button>
      </div>
      <div className="palette-presets" aria-label={t("Готовые палитры", "Preset palettes")}>
        {palettes.map((palette) => (
          <button key={palette.id} onClick={() => { onChange(palette.colors, gradient); setValue(palette.colors.join(", ")); setError(""); }}>
            <span aria-hidden="true" className="palette-dots">
              {palette.colors.map((color) => <i key={color} style={{ backgroundColor: color }} />)}
            </span>
            {t(palette.label, ({ contrast: "Contrast", lavender: "Lavender", marine: "Marine" } as Record<string, string>)[palette.id] ?? palette.label)}
          </button>
        ))}
      </div>
      <div className="palette-controls">
        <label>{t("Первый ряд", "First series")}<input aria-label={t("Первый цвет", "First color")} type="color" value={colors[0]} onChange={(event) => onChange([event.target.value, ...colors.slice(1)], gradient)} /></label>
        <label>{t("Второй ряд", "Second series")}<input aria-label={t("Второй цвет", "Second color")} type="color" value={colors[1]} onChange={(event) => onChange([colors[0], event.target.value, ...colors.slice(2)], gradient)} /></label>
        <label className="gradient-toggle"><input type="checkbox" checked={gradient} onChange={(event) => onChange(colors, event.target.checked)} /> {t("Градиент под линиями", "Gradient below lines")}</label>
      </div>
      <label className="palette-text">{t("Своя палитра", "Custom palette")}
        <div>
          <input aria-label={t("Своя палитра", "Custom palette")} value={value} onChange={(event) => setValue(event.target.value)} placeholder="#518ed5, #ddaa65" />
          <button onClick={() => apply()}>{t("Применить", "Apply")}</button>
          <button onClick={() => input.current?.click()}>{t("Загрузить файл", "Upload file")}</button>
          <input ref={input} hidden type="file" accept=".json,.txt" onChange={(event) => void upload(event.target.files?.[0])} />
        </div>
        <small>{t("JSON-массив или текст: от 2 до 12 цветов HEX.", "JSON array or text: 2–12 HEX colors.")}</small>
      </label>
      {error && <p className="palette-error" role="alert">{error}</p>}
    </section>
  );
}
