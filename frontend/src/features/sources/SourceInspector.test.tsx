import { useState } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { SourceInspector } from "./SourceInspector";
import { api, type Profile, type Source, type SourceSchema } from "../../api";
import type { Entry, View } from "../chat/types";

const source: Source = {
  source_id: "A",
  name: "Продажи",
  source_type: "csv",
  status: "available",
  created_at: "2026-10-18",
  schema_version: 1,
};
const schema: SourceSchema = {
  source_id: "A",
  version: 1,
  objects: [
    {
      object_id: "A:table",
      name: "sales",
      object_type: "csv_table",
      row_count: 2000,
      fields: [
        {
          name: "region",
          inferred_type: "string",
          nullable: true,
          is_identifier_candidate: false,
        },
        {
          name: "revenue",
          inferred_type: "number",
          nullable: false,
          is_identifier_candidate: false,
        },
      ],
    },
  ],
};
const profile: Profile = {
  sample_size: 4,
  sample_limit: 500,
  note: "Bounded sample",
  columns: {
    region: {
      sample_null_count: 1,
      sample_non_null_count: 3,
      distinct_sample_values: 2,
      top_values: [
        { value: "Север", count: 2 },
        { value: "Юг", count: 1 },
      ],
    },
    revenue: {
      sample_null_count: 0,
      sample_non_null_count: 4,
      distinct_sample_values: 4,
      top_values: [
        { value: "100", count: 1 },
        { value: "200", count: 1 },
      ],
    },
  },
};
function setup(data = profile) {
  vi.spyOn(api, "schema").mockResolvedValue(schema);
  vi.spyOn(api, "profile").mockResolvedValue(data);
  vi.spyOn(api, "preview").mockResolvedValue([
    { region: "Север", revenue: 100 },
  ]);
}
function Workspace({
  current = source,
  entry,
  initial = "overview" as View,
}: {
  current?: Source;
  entry?: Entry;
  initial?: View;
}) {
  const [view, setView] = useState<View>(initial);
  return (
    <SourceInspector
      source={current}
      entry={entry}
      view={view}
      setView={setView}
    />
  );
}

it("opens an overview with cell completeness explicitly scoped to the sample", async () => {
  setup();
  render(<Workspace />);
  expect(
    await screen.findByRole("heading", { name: "Обзор данных" }),
  ).toBeInTheDocument();
  expect(screen.getByText("87,5%")).toBeInTheDocument();
  expect(screen.getByText(/Выборка: 4 строки/)).toBeInTheDocument();
  expect(screen.getByText("2 000")).toBeInTheDocument();
  expect(screen.queryByText(/оценка качества/i)).not.toBeInTheDocument();
});

it("drills down from missing cells to a column and searches columns", async () => {
  setup();
  render(<Workspace />);
  await screen.findByRole("heading", { name: "Обзор данных" });
  fireEvent.click(screen.getByRole("button", { name: "Качество" }));
  fireEvent.click(screen.getByRole("button", { name: "Изучить region" }));
  const column = await screen.findByRole("region", { name: "Столбец region" });
  expect(within(column).getByText("25%")).toBeInTheDocument();
  expect(within(column).getByText("Север")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Поиск столбца" }), {
    target: { value: "REVENUE" },
  });
  expect(
    screen.getByRole("region", { name: "Столбец revenue" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Столбец region" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Поиск столбца" }), {
    target: { value: "нет_такого" },
  });
  expect(screen.getByText("Столбцы не найдены")).toBeInTheDocument();
});

it("does not equate an empty or incomplete profile with perfect completeness", async () => {
  setup({ ...profile, sample_size: 0, columns: {} });
  render(<Workspace />);
  expect(await screen.findByText("В выборке нет строк")).toBeInTheDocument();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getAllByText("Статистика столбца недоступна")).toHaveLength(2);
});

it("marks partial coverage rather than counting unprofiled columns as filled", async () => {
  setup({ ...profile, columns: { region: profile.columns.region } });
  render(<Workspace />);
  expect(
    await screen.findByText(/Профиль доступен для 1 из 2 столбцов/),
  ).toBeInTheDocument();
  expect(screen.getByText("75%")).toBeInTheDocument();
});

it("clears old analytics while a different source is loading", async () => {
  setup();
  const { rerender } = render(<Workspace />);
  await screen.findByRole("heading", { name: "Обзор данных" });
  let finish!: (value: Profile) => void;
  vi.mocked(api.profile).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.mocked(api.schema).mockResolvedValue({ ...schema, source_id: "B" });
  rerender(
    <Workspace
      current={{ ...source, source_id: "B", name: "Другой источник" }}
    />,
  );
  expect(screen.queryByText("87,5%")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Изучаем структуру");
  await act(async () => finish({ ...profile, sample_size: 0, columns: {} }));
  expect(await screen.findByText("В выборке нет строк")).toBeInTheDocument();
});

it("shows the actual answer safely in the analysis pane with its table", async () => {
  setup();
  const entry: Entry = {
    id: "q1",
    question: "Где выручка выше?",
    state: "success",
    answer: {
      answer:
        "**Север** лидирует.\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))",
      steps: 1,
      tool_results: [
        {
          tool_name: "execute_sql",
          ok: true,
          data: [{ region: "Север", revenue: 200 }],
        },
      ],
    },
  };
  const { container } = render(<Workspace entry={entry} initial="results" />);
  expect(
    await screen.findByRole("heading", { name: "Результат анализа" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Север", { selector: "strong" })).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Результат execute_sql" }),
  ).toBeInTheDocument();
  expect(
    container.querySelector("script, iframe, a[href^='javascript:']"),
  ).toBeNull();
});
