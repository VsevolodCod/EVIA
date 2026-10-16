export type Mood = "waiting" | "busy" | "error" | "success";
export function Evia({
  mood = "waiting",
  large = false,
}: {
  mood?: Mood;
  large?: boolean;
}) {
  return (
    <div
      className={`evia evia-${mood} ${large ? "evia-large" : ""}`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 140 145" fill="none">
        <ellipse
          className="evia-shadow"
          cx="71"
          cy="132"
          rx="28"
          ry="4"
          fill="#D9E1D7"
        />
        <g className="evia-body">
          <path
            d="M55 83h32v25c0 9-7 15-16 15s-16-6-16-15V83Z"
            fill="#E4EDE0"
            stroke="#577859"
            strokeWidth="1.5"
          />
          <path
            d="m51 91-8 16m48-16 8 13"
            stroke="#577859"
            strokeWidth="7"
            strokeLinecap="round"
          />
          <path
            d="M61 120v7m19-7v7"
            stroke="#32563C"
            strokeWidth="7"
            strokeLinecap="round"
          />
          <rect x="64" y="96" width="14" height="5" rx="2.5" fill="#8DB78A" />
        </g>
        <g className="evia-head">
          <path d="M70 29v-8" stroke="#577859" strokeWidth="2" />
          <circle cx="70" cy="18" r="4" fill="#A5C795" />
          <rect
            x="29"
            y="31"
            width="84"
            height="55"
            rx="25"
            fill="#E4EDE0"
            stroke="#577859"
            strokeWidth="1.5"
          />
          <rect x="39" y="41" width="64" height="35" rx="15" fill="#244A36" />
          {mood === "success" ? (
            <path
              d="m51 56 5-4 5 4m20 0 5-4 5 4"
              stroke="#E8F5CB"
              strokeWidth="3"
              strokeLinecap="round"
            />
          ) : mood === "error" ? (
            <path
              d="m51 51 10 4m20 0 10-4M55 60v3m31-3v3"
              stroke="#E8F5CB"
              strokeWidth="3"
              strokeLinecap="round"
            />
          ) : (
            <g className="evia-eyes">
              <rect
                x="53"
                y="50"
                width="5"
                height={mood === "busy" ? 5 : 10}
                rx="2.5"
                fill="#E8F5CB"
              />
              <rect
                x="84"
                y="50"
                width="5"
                height={mood === "busy" ? 5 : 10}
                rx="2.5"
                fill="#E8F5CB"
              />
            </g>
          )}
          <path
            d={mood === "error" ? "M67 68q4-4 8 0" : "M66 65q5 5 10 0"}
            stroke="#E8F5CB"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <path
            d="M31 56h-4m88 0h-4"
            stroke="#577859"
            strokeWidth="5"
            strokeLinecap="round"
          />
        </g>
      </svg>
    </div>
  );
}
