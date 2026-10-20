import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import type { Profile, SourceSchema } from "../../api";
import { Dashboard } from "./Dashboard";

const schema: SourceSchema = {
  source_id: "trips",
  version: 1,
  objects: [{
    object_id: "trips:table", name: "trips", object_type: "csv_table", row_count: 3,
    fields: [
      { name: "city", inferred_type: "string", nullable: false, is_identifier_candidate: false },
      { name: "distance", inferred_type: "number", nullable: false, is_identifier_candidate: false },
      { name: "day", inferred_type: "date", nullable: false, is_identifier_candidate: false },
    ],
  }],
};
const rows = [
  { city: "Новосибирск", distance: 3.2, day: "2026-01-01" },
  { city: "Томск", distance: 5.1, day: "2026-01-01" },
  { city: "Новосибирск", distance: 4.4, day: "2026-01-02" },
];

const profile: Profile = {
  sample_size: 3,
  sample_limit: 500,
  note: "Профиль построен по выборке",
  columns: {
    city: {
      sample_non_null_count: 2,
      sample_null_count: 1,
      distinct_sample_values: 2,
      top_values: [
        { value: "Новосибирск", count: 1 },
        { value: "Томск", count: 1 },
      ],
    },
    distance: {
      sample_non_null_count: 3,
      sample_null_count: 0,
      distinct_sample_values: 3,
      top_values: [],
    },
    day: {
      sample_non_null_count: 3,
      sample_null_count: 0,
      distinct_sample_values: 2,
      top_values: [],
    },
  },
};

it("shows compact factual metrics and charts from source rows", () => {
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="trips" schema={schema} rows={rows} fullSourceRows={3} />);

  expect(screen.getByRole("heading", { name: "Поездки" })).toBeInTheDocument();
  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Динамика по полю day/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Распределение поля distance/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Частые значения поля city/ })).toBeInTheDocument();
  expect(screen.getByText(/3 строки в предпросмотре источника/)).toBeInTheDocument();
});

it("separates the full source from profile coverage and highlights data quality", () => {
  render(
    <Dashboard
      title="Поездки"
      sourceLabel="Поездки.csv"
      scope="trips"
      schema={{
        ...schema,
        objects: [{ ...schema.objects[0], row_count: 2_000 }],
      }}
      rows={rows}
      profile={profile}
      fullSourceRows={2_000}
    />,
  );

  expect(screen.getByText("Строк в источнике")).toBeInTheDocument();
  expect(screen.getByText("2 000")).toBeInTheDocument();
  expect(screen.getByText("Профиль покрывает")).toBeInTheDocument();
  expect(screen.getByText("3 строки")).toBeInTheDocument();
  expect(screen.getByText("выборка до 500 строк")).toBeInTheDocument();
  expect(screen.getByText("Нужна проверка")).toBeInTheDocument();
  expect(screen.getByText("1 поле с пропусками")).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: /Пропуски по столбцам: city: 33,3%/ }),
  ).toBeInTheDocument();
});

it("uses a readable plural form for several fields with missing values", () => {
  render(
    <Dashboard
      title="Поездки"
      sourceLabel="Поездки.csv"
      scope="plural-quality"
      schema={schema}
      rows={rows}
      profile={{
        ...profile,
        columns: {
          ...profile.columns,
          distance: { ...profile.columns.distance, sample_null_count: 1 },
        },
      }}
      fullSourceRows={3}
    />,
  );

  expect(screen.getByText("2 поля с пропусками")).toBeInTheDocument();
});

it("does not present a preview as the full source when its row count is unavailable", () => {
  render(
    <Dashboard
      title="Поездки"
      sourceLabel="Поездки.csv"
      scope="unknown-row-count"
      schema={{ ...schema, objects: [{ ...schema.objects[0], row_count: null }] }}
      rows={rows}
      profile={profile}
      fullSourceRows={null}
    />,
  );

  expect(screen.getByText("Строк в предпросмотре")).toBeInTheDocument();
  expect(screen.getByText("Полный объём неизвестен")).toBeInTheDocument();
});

it("does not call an empty profile clean data", () => {
  render(
    <Dashboard
      title="Поездки"
      sourceLabel="Поездки.csv"
      scope="empty-profile"
      schema={schema}
      rows={[]}
      profile={{ ...profile, sample_size: 0, columns: {} }}
      fullSourceRows={3}
    />,
  );

  expect(screen.getByText("Нет профиля")).toBeInTheDocument();
  expect(screen.getByText("Нет строк для проверки")).toBeInTheDocument();
  expect(screen.queryByText("Без пропусков")).not.toBeInTheDocument();
});

it("applies a valid custom palette, rejects bad input and opens the print dialog", () => {
  const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="palette-test" schema={schema} rows={rows} />);
  expect(screen.getByTestId("print-report")).toHaveAttribute("data-print-report", "true");

  fireEvent.click(screen.getByRole("button", { name: "Цвета" }));
  const input = screen.getByLabelText("Своя палитра");
  fireEvent.change(input, { target: { value: "#2563eb, #bf5e47" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(screen.getByTestId("chart-color-0")).toHaveAttribute("data-color", "#2563eb");

  fireEvent.change(input, { target: { value: "red" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(screen.getByRole("alert")).toHaveTextContent("#RRGGBB");
  expect(screen.getByTestId("chart-color-0")).toHaveAttribute("data-color", "#2563eb");

  const pageTitle = document.title;
  fireEvent.click(screen.getByRole("button", { name: "Экспорт PDF" }));
  expect(print).toHaveBeenCalledOnce();
  expect(document.title).toBe("EVIA — Поездки");
  window.dispatchEvent(new Event("afterprint"));
  expect(document.title).toBe(pageTitle);
});

it("imports a palette file and applies the optional line gradient", async () => {
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="palette-import" schema={schema} rows={rows} />);
  fireEvent.click(screen.getByRole("button", { name: "Цвета" }));
  const file = new File(["unused"], "palette.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve('["#112233", "#445566"]') });
  const upload = document.querySelector('input[type="file"]');
  expect(upload).not.toBeNull();
  fireEvent.change(upload!, { target: { files: [file] } });
  await waitFor(() => expect(screen.getByTestId("chart-color-0")).toHaveAttribute("data-color", "#112233"));

  fireEvent.click(screen.getByLabelText("Градиент под линиями"));
  expect(document.querySelector(".line-chart path")).not.toBeNull();
});

it("explains the absence of charts without inventing analytics", () => {
  render(<Dashboard title="Идентификаторы" sourceLabel="ids.csv" scope="ids" schema={{ ...schema, objects: [{ ...schema.objects[0], fields: [{ name: "id", inferred_type: "integer", nullable: false, is_identifier_candidate: true }] }] }} rows={[{ id: 1 }]} />);
  expect(screen.getByText("Для графиков нужны числовые, текстовые или временные поля.")).toBeInTheDocument();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("opens and closes a chart detail without losing its values", () => {
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="mobile-chart" schema={schema} rows={rows} />);
  fireEvent.click(screen.getByRole("button", { name: "Развернуть график Частые значения: city" }));
  expect(screen.getByRole("button", { name: "Закрыть график" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Частые значения поля city" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Закрыть график" }));
  expect(screen.getByRole("button", { name: "Развернуть график Частые значения: city" })).toBeInTheDocument();
});

it("exports preview rows as a CSV from the mobile export sheet", () => {
  const createObjectURL = vi.fn(() => "blob:trips");
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="mobile-export" schema={schema} rows={rows} />);
  fireEvent.click(screen.getByRole("button", { name: "Экспорт" }));
  expect(screen.getByRole("region", { name: "Экспорт результатов" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Скачать CSV/ }));
  expect(createObjectURL).toHaveBeenCalledTimes(1);
  expect(click).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("region", { name: "Экспорт результатов" })).not.toBeInTheDocument();
});
