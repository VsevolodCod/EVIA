import { fireEvent, render, screen } from "@testing-library/react";
import { DataTable, SafeMarkdown, ToolResults } from "./components";
it("renders GFM tables and emphasis while blocking HTML, images and unsafe links", () => {
  const { container } = render(
    <SafeMarkdown>
      {
        "**Итог**\n\n| Поле | Значение |\n| --- | --- |\n| x | 1 |\n\n<script>alert(1)</script>\n\n![remote](https://evil.test/pixel)\n\n[bad](javascript:alert%281%29)\n\n[good](https://example.com)"
      }
    </SafeMarkdown>,
  );
  expect(screen.getByText("Итог").tagName).toBe("STRONG");
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(container.querySelector("script, img, iframe")).toBeNull();
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(screen.getByRole("link", { name: "good" })).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
});
it("shows explicit empty rows and does not infer an empty table as an analysis", () => {
  render(<DataTable rows={[]} />);
  expect(screen.getByText("Нет строк для отображения")).toBeInTheDocument();
});
it("preserves heterogeneous tool payloads and tool failures as distinct results", () => {
  render(
    <ToolResults
      results={[
        { tool_name: "preview_source", ok: true, data: [] },
        {
          tool_name: "profile_source",
          ok: true,
          data: { sample_size: 2, note: "bounded" },
        },
        { tool_name: "bad_tool", ok: false, data: null, error: "Tool failed" },
      ]}
    />,
  );
  expect(screen.getByText("Нет строк для отображения")).toBeInTheDocument();
  expect(screen.getByText(/"sample_size": 2/)).toBeInTheDocument();
  expect(screen.getByText("Tool failed")).toBeInTheDocument();
});
it("paginates large results and resets pagination when the result changes", () => {
  const rows = Array.from({ length: 55 }, (_, i) => ({
    code: `unique-row-${i}`,
  }));
  const { rerender } = render(<DataTable rows={rows} />);
  expect(screen.getByText("unique-row-0")).toBeInTheDocument();
  expect(screen.queryByText("unique-row-54")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Следующие строки" }));
  expect(screen.getByText("unique-row-25")).toBeInTheDocument();
  rerender(<DataTable rows={[{ code: "new-source" }]} />);
  expect(screen.getByText("new-source")).toBeInTheDocument();
});
