import { EviaMascot } from "../../components/EviaMascot";
import type { EviaState } from "../mascot/states";

export function Evia({
  state = "waiting",
  large = false,
}: {
  state?: EviaState;
  large?: boolean;
}) {
  return (
    <EviaMascot
      state={state}
      size={large ? 144 : 72}
      decorative
      className={large ? "evia-large" : ""}
    />
  );
}
