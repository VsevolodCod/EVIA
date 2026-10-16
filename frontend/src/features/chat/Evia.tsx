import { EviaMascot } from "../../components/EviaMascot";
import type { EviaState } from "../mascot/states";

export function Evia({
  state = "waiting",
  large = false,
  quiet = false,
}: {
  state?: EviaState;
  large?: boolean;
  quiet?: boolean;
}) {
  return (
    <EviaMascot
      state={state}
      size={large ? 144 : 72}
      quiet={quiet}
      decorative
      className={large ? "evia-large" : ""}
    />
  );
}
