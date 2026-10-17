import { useState } from "react";
import { EviaMascot } from "../../components/EviaMascot";
import { EVIA_STATES, eviaLabel, type EviaState } from "./states";
import "./gallery.css";

export default function MascotGallery() {
  const [state, setState] = useState<EviaState>("welcome");
  const [size, setSize] = useState(128);
  const [quiet, setQuiet] = useState(false);
  return (
    <main className="mascot-gallery">
      <header>
        <a href={import.meta.env.BASE_URL}>← В рабочее пространство</a>
        <p className="eyebrow">EVIA · библиотека персонажа</p>
        <h1>EVIA · 40 состояний</h1>
        <p>Ваш набор SVG — эмоции, работа с данными и системные события.</p>
      </header>
      <section className="mascot-preview" aria-label="Выбранное состояние">
        <div className="mascot-preview-stage">
          <EviaMascot state={state} size={size} quiet={quiet} />
        </div>
        <div className="mascot-preview-controls">
          <h2>{eviaLabel(state)}</h2>
          <code>{state}</code>
          <p>
            Это предпросмотр. В приложении состояние меняется только по
            реальному событию.
          </p>
          <label>
            Размер маскота
            <select
              aria-label="Размер маскота"
              value={size}
              onChange={(event) => setSize(Number(event.target.value))}
            >
              {[64, 96, 128, 192, 256].map((value) => (
                <option key={value} value={value}>
                  {value} px
                </option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={quiet}
              onChange={(event) => setQuiet(event.target.checked)}
            />{" "}
            Без анимации
          </label>
          <small>
            Системная настройка уменьшения движения учитывается автоматически.
          </small>
        </div>
      </section>
      <div className="mascot-state-grid" aria-label="Все состояния EVIA">
        {EVIA_STATES.map((item) => (
          <button
            key={item.id}
            aria-label={`Выбрать: ${item.label}`}
            aria-pressed={state === item.id}
            onClick={() => setState(item.id)}
          >
            <EviaMascot state={item.id} size={112} decorative quiet />
            <strong>{item.label}</strong>
            <code>{item.id}</code>
          </button>
        ))}
      </div>
      <footer>
        Векторный набор EVIA предоставлен автором проекта. Состояния графиков,
        дашбордов и этапов вычисления готовы для будущих событий API.
      </footer>
    </main>
  );
}
