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
  snapshot_id: "sales-snapshot-001",
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
        {
          name: "created_at",
          inferred_type: "datetime",
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
  processed_rows: 2_000,
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
      non_null_count: 1_900,
      null_count: 100,
      empty_count: 20,
      distinct_count: 87,
      uniqueness_ratio: 87 / 1_900,
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
      non_null_count: 2_000,
      null_count: 0,
      empty_count: 0,
      distinct_count: 2_000,
      uniqueness_ratio: 1,
      is_identifier_candidate: true,
      top_values_coverage: "sample",
      numeric: {
        count: 2_000,
        minimum: "0.000000123456789",
        maximum: "9876543210.123456789",
        total: "12345678901.23456789",
        average: "6172839.450617283945",
      },
    },
    created_at: {
      sample_null_count: 0,
      sample_non_null_count: 4,
      distinct_sample_values: 4,
      top_values: [],
      non_null_count: 2_000,
      null_count: 0,
      empty_count: 0,
      distinct_count: 2_000,
      uniqueness_ratio: 1,
      is_identifier_candidate: false,
      top_values_coverage: "sample",
      temporal: {
        count: 2_000,
        minimum: "2024-01-01T00:00:00.000001Z",
        maximum: "2026-10-22T23:59:59.999999Z",
      },
    },
  },
};

const sampledProfile: Profile = {
  sample_size: 4,
  sample_limit: 500,
  coverage: "sample",
  note: "Профиль построен по выборке.",
  columns: {
    region: {
      sample_null_count: 1,
      sample_non_null_count: 3,
      distinct_sample_values: 2,
      top_values: [{ value: "Север", count: 2 }],
    },
    revenue: {
      sample_null_count: 0,
      sample_non_null_count: 4,
      distinct_sample_values: 4,
      top_values: [{ value: "100", count: 1 }],
    },
    created_at: {
      sample_null_count: 0,
      sample_non_null_count: 4,
      distinct_sample_values: 4,
      top_values: [],
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
  expect(await screen.findByRole("heading", { name: "Обзор источника" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Продажи" })).toBeInTheDocument();
  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByText("2 000")).toBeInTheDocument();
  expect(screen.queryByText(/1 строка в предпросмотре источника/)).not.toBeInTheDocument();
  expect(screen.getByText("Полный датасет")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Первые строки источника" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Открыть данные/ }));
  expect(await screen.findByRole("heading", { name: "Предпросмотр данных" })).toBeInTheDocument();
});

it("places the source identity above its sections and keeps results contextual", async () => {
  setup();
  const { container } = render(<Workspace initial="profile" />);
  const title = await screen.findByRole("heading", { name: "Продажи" });
  const navigation = container.querySelector(".analytics-tabs");
  expect(navigation).not.toBeNull();
  expect(title.compareDocumentPosition(navigation!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Результат анализа" })).not.toBeInTheDocument();
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
  await screen.findByRole("heading", { name: "Обзор источника" });
  fireEvent.click(screen.getByRole("button", { name: "Качество" }));
  expect(screen.queryByText(/Точные NULL по всему датасету/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Изучить region" }));
  const column = await screen.findByRole("region", { name: "Столбец region" });
  expect(within(column).getAllByText("5%")).toHaveLength(1);
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

it("labels full CSV statistics as exact while keeping top values scoped to the sample", async () => {
  setup();
  render(<Workspace initial="profile" />);

  expect(await screen.findByRole("region", { name: "Столбец revenue" })).toBeInTheDocument();
  expect(document.querySelector(".profile-scope")).toBeNull();
  expect(screen.queryByText("Статистика по всему датасету")).not.toBeInTheDocument();
  expect(screen.queryByText("ИССЛЕДУЙТЕ ДЕТАЛИ")).not.toBeInTheDocument();
  expect(screen.queryByText(/строк в источнике/)).not.toBeInTheDocument();

  const revenue = screen.getByRole("region", { name: "Столбец revenue" });
  fireEvent.click(revenue.querySelector("summary")!);
  expect(within(revenue).getByText("Заполнено")).toBeInTheDocument();
  expect(within(revenue).getByText("NULL")).toBeInTheDocument();
  expect(within(revenue).getByText("Пустые строки")).toBeInTheDocument();
  expect(within(revenue).getByText("Уникальных значений")).toBeInTheDocument();
  expect(within(revenue).getByText("Уникальность")).toBeInTheDocument();
  expect(within(revenue).getAllByText("2 000")).toHaveLength(2);
  expect(within(revenue).getByText(/Гипотеза: кандидат в идентификаторы/)).toBeInTheDocument();
  expect(within(revenue).getByText("Диапазон чисел")).toBeInTheDocument();
  expect(within(revenue).getByText("0.000000123456789 — 9876543210.123456789")).toBeInTheDocument();
  expect(within(revenue).getByText("Частые значения — только по выборке")).toBeInTheDocument();
  expect(within(revenue).getByText("4 строки в выборке")).toBeInTheDocument();

  const createdAt = screen.getByRole("region", { name: "Столбец created_at" });
  fireEvent.click(createdAt.querySelector("summary")!);
  expect(within(createdAt).getByText("Диапазон дат")).toBeInTheDocument();
  expect(within(createdAt).getByText("2024-01-01T00:00:00.000001Z — 2026-10-22T23:59:59.999999Z")).toBeInTheDocument();
});

it("labels profile grain candidates as hypotheses rather than confirmed keys", async () => {
  setup({
    ...profile,
    candidate_grain_keys: [["region", "created_at"]],
  });
  render(<Workspace initial="profile" />);

  expect(await screen.findByText("Гипотезы о ключе строк")).toBeInTheDocument();
  expect(screen.getByText("region + created_at")).toBeInTheDocument();
  expect(screen.getByText(/требует проверки/)).toBeInTheDocument();
});

it("keeps PostgreSQL sample profiles visibly limited to sampled statistics", async () => {
  setup(sampledProfile);
  render(<Workspace initial="profile" />);

  expect(await screen.findByRole("region", { name: "Столбец region" })).toBeInTheDocument();
  expect(document.querySelector(".profile-scope")).toBeNull();
  expect(screen.queryByText("Статистика относится к выборке, а не ко всему источнику.")).not.toBeInTheDocument();
  expect(screen.queryByText("Статистика по всему датасету")).not.toBeInTheDocument();
  const region = screen.getByRole("region", { name: "Столбец region" });
  fireEvent.click(region.querySelector("summary")!);
  expect(within(region).getByText("Количество в выборке")).toBeInTheDocument();
  expect(within(region).queryByText("NULL")).not.toBeInTheDocument();
  expect(within(region).queryByText("Пустые строки")).not.toBeInTheDocument();
  expect(within(region).queryByText("Уникальность")).not.toBeInTheDocument();
});

it("rejects an exact profile created for a different source snapshot", async () => {
  setup({ ...profile, snapshot_id: "stale-snapshot" });
  render(<Workspace current={{ ...source, snapshot_id: "current-snapshot" }} initial="profile" />);

  expect(await screen.findByText(/другой версии источника/i)).toBeInTheDocument();
  expect(screen.queryByText("Статистика по всему датасету")).not.toBeInTheDocument();
});

it("keeps an empty preview distinct from an incomplete profile", async () => {
  setup({ ...profile, sample_size: 0, columns: {} });
  vi.mocked(api.preview).mockResolvedValue([]);
  render(<Workspace />);
  expect(await screen.findByText("В предпросмотре нет строк")).toBeInTheDocument();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getAllByText("Статистика столбца недоступна")).toHaveLength(3);
});

it("keeps source dashboard calculations tied to preview rather than profile coverage", async () => {
  setup({ ...profile, columns: { region: profile.columns.region } });
  render(<Workspace />);
  expect(
    await screen.findByRole("heading", { name: "Обзор источника" }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/1 строка в предпросмотре источника/)).not.toBeInTheDocument();
});

it("keeps the overview available when the profile request fails", async () => {
  setup();
  vi.mocked(api.profile).mockRejectedValueOnce(new Error("Профиль временно недоступен"));
  render(<Workspace />);

  expect(await screen.findByRole("heading", { name: "Обзор источника" })).toBeInTheDocument();
  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByText("Полный датасет")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Данные" }));
  expect(await screen.findByRole("region", { name: "Предпросмотр источника" })).toBeInTheDocument();
});

it("clears old analytics while a different source is loading", async () => {
  setup();
  const { rerender } = render(<Workspace />);
  await screen.findByRole("heading", { name: "Обзор источника" });
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

it("shows the calculation without duplicating the chat answer", async () => {
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
  expect(screen.queryByText("лидирует.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Таблица и детали расчёта"));
  expect(screen.getByRole("region", { name: "Результат execute_sql" })).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "Распределение поля revenue" }),
  ).toBeInTheDocument();
  expect(
    container.querySelector("script, iframe, a[href^='javascript:']"),
  ).toBeNull();
});
