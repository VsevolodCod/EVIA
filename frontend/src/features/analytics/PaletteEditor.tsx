import { useRef, useState } from "react";
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
      setError(reason instanceof Error ? reason.message : "Не удалось прочитать палитру.");
    }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    if (file.size > 16 * 1024) {
      setError("Файл палитры больше 16 КБ.");
      return;
    }
    try {
      apply(await file.text());
    } catch {
      setError("Не удалось прочитать файл палитры.");
    }
  };

  return (
    <section className="palette-editor" aria-label="Настройка цветов графиков">
      <div className="palette-editor-heading">
        <strong>Цвета графиков</strong>
        <button className="palette-close" aria-label="Закрыть цвета" onClick={onClose}>×</button>
      </div>
      <div className="palette-presets" aria-label="Готовые палитры">
        {palettes.map((palette) => (
          <button key={palette.id} onClick={() => { onChange(palette.colors, gradient); setValue(palette.colors.join(", ")); setError(""); }}>
            <span aria-hidden="true" className="palette-dots">
              {palette.colors.map((color) => <i key={color} style={{ backgroundColor: color }} />)}
            </span>
            {palette.label}
          </button>
        ))}
      </div>
      <div className="palette-controls">
        <label>Первый ряд<input aria-label="Первый цвет" type="color" value={colors[0]} onChange={(event) => onChange([event.target.value, ...colors.slice(1)], gradient)} /></label>
        <label>Второй ряд<input aria-label="Второй цвет" type="color" value={colors[1]} onChange={(event) => onChange([colors[0], event.target.value, ...colors.slice(2)], gradient)} /></label>
        <label className="gradient-toggle"><input type="checkbox" checked={gradient} onChange={(event) => onChange(colors, event.target.checked)} /> Градиент под линиями</label>
      </div>
      <label className="palette-text">Своя палитра
        <div>
          <input aria-label="Своя палитра" value={value} onChange={(event) => setValue(event.target.value)} placeholder="#518ed5, #ddaa65" />
          <button onClick={() => apply()}>Применить</button>
          <button onClick={() => input.current?.click()}>Загрузить файл</button>
          <input ref={input} hidden type="file" accept=".json,.txt" onChange={(event) => void upload(event.target.files?.[0])} />
        </div>
        <small>JSON-массив или текст: от 2 до 12 цветов HEX.</small>
      </label>
      {error && <p className="palette-error" role="alert">{error}</p>}
    </section>
  );
}
