import type { ReactNode } from "react";

type IconName =
  | "plus"
  | "file"
  | "arrow"
  | "chat"
  | "refresh"
  | "check"
  | "grid"
  | "upload"
  | "chevron"
  | "close"
  | "home"
  | "user"
  | "back"
  | "settings";
const paths: Record<IconName, ReactNode> = {
  plus: <path d="M12 5v14M5 12h14" />,
  file: (
    <>
      <path d="M14 3H6a1 1 0 0 0-1 1v16h14V8zM14 3v5h5M8 12h8M8 16h8M12 12v7" />
    </>
  ),
  arrow: <path d="M12 19V5m-6 6 6-6 6 6" />,
  chat: <path d="M20 11a8 8 0 0 1-8 8H4l1.5-4A8 8 0 1 1 20 11Z" />,
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  grid: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M4 10h16M10 4v16M4 15h16" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15V3m-4 4 4-4 4 4M5 14v6h14v-6" />
    </>
  ),
  chevron: <path d="m9 5 7 7-7 7" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  home: <path d="m3 10 9-7 9 7v10h-6v-6H9v6H3z" />,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  back: <path d="m15 18-6-6 6-6" />,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l-1.86 1.86A1.7 1.7 0 0 0 16 18.4a1.7 1.7 0 0 0-1.5.89L13.6 21h-3.2l-.9-1.71A1.7 1.7 0 0 0 8 18.4a1.7 1.7 0 0 0-1.88.34l-1.86-1.86A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.89-1.5L2 12.6V11.4l1.71-.9A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.88l1.86-1.86A1.7 1.7 0 0 0 8 5.6a1.7 1.7 0 0 0 1.5-.89L10.4 3h3.2l.9 1.71A1.7 1.7 0 0 0 16 5.6a1.7 1.7 0 0 0 1.88-.34l1.86 1.86A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 .89 1.5l1.71.9v1.2l-1.71.9A1.7 1.7 0 0 0 19.4 15Z" /></>,
};
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
