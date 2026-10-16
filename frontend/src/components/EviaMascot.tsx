import { eviaLabel, type EviaState } from "../features/mascot/states";
import "../features/mascot/mascot.css";
export type { EviaState } from "../features/mascot/states";

export type EviaMascotProps = {
  state?: EviaState;
  size?: number;
  className?: string;
  decorative?: boolean;
  quiet?: boolean;
};

/** Artwork is served as an isolated image; no SVG markup is injected into the DOM. */
export function EviaMascot({
  state = "idle",
  size = 112,
  className = "",
  decorative = false,
  quiet = false,
}: EviaMascotProps) {
  return (
    <span
      className={`evia-mascot ${className}`}
      data-evia-state={state}
      data-motion={quiet ? "off" : "on"}
      style={{ width: size, height: size }}
      aria-hidden={decorative || undefined}
    >
      <img
        key={state}
        src={`${import.meta.env.BASE_URL}mascot/${state}.svg`}
        width={size}
        height={size}
        alt={decorative ? "" : `Эвия — ${eviaLabel(state)}`}
        draggable={false}
      />
    </span>
  );
}
