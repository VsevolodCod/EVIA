import { useEffect, useState } from "react";
import { Evia } from "../chat/Evia";
import type { EviaState } from "./states";

export const welcomeGreetings: { text: string; state: EviaState }[] = [
  { text: "Привет! Давай найдём ответ в данных.", state: "welcome" },
  { text: "Я рядом, если захочешь исследовать таблицу.", state: "suggestion" },
  { text: "Начнём с данных — дальше разберёмся вместе.", state: "listening" },
  { text: "Готова помочь с вопросами и графиками.", state: "insight" },
];

export function WelcomeGreeting({ greeting, activeState }: {
  greeting: { text: string; state: EviaState };
  activeState: EviaState;
}) {
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const [started, setStarted] = useState(reducedMotion);
  const [length, setLength] = useState(reducedMotion ? greeting.text.length : 0);

  useEffect(() => {
    if (reducedMotion) return;
    let typing: number | undefined;
    const delay = window.setTimeout(() => {
      setStarted(true);
      typing = window.setInterval(() => {
        setLength((current) => {
          if (current >= greeting.text.length) {
            window.clearInterval(typing);
            return current;
          }
          return current + 1;
        });
      }, 42);
    }, 480);
    return () => { window.clearTimeout(delay); window.clearInterval(typing); };
  }, [greeting.text, reducedMotion]);

  const state = ["welcome", "waiting", "listening"].includes(activeState) ? greeting.state : activeState;
  return <div className="evia-greeting-block">
    {started && <div className="evia-greeting" aria-label="Приветствие EVIA" data-typing={length < greeting.text.length}>
      <span aria-hidden="true">{greeting.text.slice(0, length)}</span>
      <span className="visually-hidden">{greeting.text}</span>
    </div>}
    <Evia large state={state} />
  </div>;
}
