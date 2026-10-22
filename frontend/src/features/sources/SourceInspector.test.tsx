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
  processed_rows: 4,
  coverage: "full",
  snapshot_id: "sales-snapshot-001",
  note: "Full dataset statistics; top values are sampled.",
  columns: {
    region: {
      sample_null_count: 1,
      sample_non_null_count: 3,
      distinct_sample_values: 2,
      top_values: [
        { value: "Север", count: 2 },
        { value: "Юг", count: 1 },
      ],
      non_null_count: 3,
      null_count: 1,
      empty_count: 0,
      distinct_count: 2,
      uniqueness_ratio: 2 / 3,
      is_identifier_candidate: false,
      top_values_coverage: "sample",
    },
    revenue: {
      sample_null_count: 0,
      sample_non_null_count: 4,
      distinct_sample_values: 4,
      top_values: [
        { value: "100", count: 1 },
        { value: "200", count: 1 },
      ],
      non_null_count: 4,
      null_count: 0,
      empty_count: 0,
      distinct_count: 4,
      uniqueness_ratio: 1,
      is_identifier_candidate: true,
      top_values_coverage: "sample",
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

it("distinguishes the full source from its preview in the dashboard", async () => {
  setup();
  render(<Workspace />);
  expect(
    await screen.findByRole("heading", { name: "Продажи" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByText("2 000")).toBeInTheDocument();
  expect(screen.getByText(/1 строка в предпросмотре источника/)).toBeInTheDocument();
  expect(screen.getByText("Полный датасет")).toBeInTheDocument();
});

it("keeps the section navigation above every analytics view", async () => {
  setup();
  const { container } = render(<Workspace initial="profile" />);
  const title = await screen.findByRole("heading", { name: "Продажи" });
  const navigation = container.querySelector(".analytics-tabs");
  expect(navigation).not.toBeNull();
  expect(navigation!.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("shows import accounting and allows replacing a CSV with a new snapshot", async () => {
  setup();
  const onReimport = vi.fn();
  render(<SourceInspector source={{
    ...source,
    snapshot_id: "snapshot-1",
    import_report: {
      sha256: "abc", size_bytes: 18, encoding: "utf-16", delimiter: ";",
      rows_read: 2, accepted_rows: 2, rejected_rows: 0, blank_lines: 0,
      warnings: [], errors: [],
    },
  }} view="schema" setView={() => {}} onReimport={onReimport} />);
  await screen.findByText("Структура источника");
  expect(screen.getByText(/Принято 2 из 2 строк/)).toBeInTheDocument();
  const file = new File(["id\n1\n"], "replacement.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("Повторно импортировать CSV"), { target: { files: [file] } });
  expect(onReimport).toHaveBeenCalledWith(file, "A");
});

it("drills down from missing cells to a column and searches columns", async () => {
  setup();
  render(<Workspace />);
  await screen.findByRole("heading", { name: "Продажи" });
  fireEvent.click(screen.getByRole("button", { name: "Качество" }));
  fireEvent.click(screen.getByRole("button", { name: "Изучить region" }));
  const column = await screen.findByRole("region", { name: "Столбец region" });
  expect(within(column).getAllByText("25%")).toHaveLength(2);
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

it("keeps an empty preview distinct from an incomplete profile", async () => {
  setup({ ...profile, sample_size: 0, columns: {} });
  vi.mocked(api.preview).mockResolvedValue([]);
  render(<Workspace />);
  expect(await screen.findByText("В предпросмотре нет строк")).toBeInTheDocument();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getAllByText("Статистика столбца недоступна")).toHaveLength(2);
});

it("keeps source dashboard calculations tied to preview rather than profile coverage", async () => {
  setup({ ...profile, columns: { region: profile.columns.region } });
  render(<Workspace />);
  expect(
    await screen.findByRole("heading", { name: "Продажи" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/1 строка в предпросмотре источника/)).toBeInTheDocument();
});

it("keeps the overview available when the profile request fails", async () => {
  setup();
  vi.mocked(api.profile).mockRejectedValueOnce(new Error("Профиль временно недоступен"));
  render(<Workspace />);

  expect(await screen.findByRole("heading", { name: "Продажи" })).toBeInTheDocument();
  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByText("Полный датасет")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Данные" }));
  expect(await screen.findByRole("region", { name: "Предпросмотр источника" })).toBeInTheDocument();
});

it("clears old analytics while a different source is loading", async () => {
  setup();
  const { rerender } = render(<Workspace />);
  await screen.findByRole("heading", { name: "Продажи" });
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
  expect(await screen.findByRole("heading", { name: "Другой источник" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Продажи" })).not.toBeInTheDocument();
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
    screen.getByRole("img", { name: "Распределение поля revenue" }),
  ).toBeInTheDocument();
  expect(
    container.querySelector("script, iframe, a[href^='javascript:']"),
  ).toBeNull();
});
