import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { SourceSchema } from "../../api";
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

it("shows compact factual metrics and charts from source rows", () => {
  render(<Dashboard title="Поездки" sourceLabel="Поездки.csv" scope="trips" schema={schema} rows={rows} />);

  expect(screen.getByRole("heading", { name: "Поездки" })).toBeInTheDocument();
  expect(screen.getByText("Строк в выборке")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Динамика по полю day/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Распределение поля distance/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Частые значения поля city/ })).toBeInTheDocument();
  expect(screen.getByText(/3 строки в предпросмотре источника/)).toBeInTheDocument();
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
