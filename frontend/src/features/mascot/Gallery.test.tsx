import { fireEvent, render, screen, within } from "@testing-library/react";
import MascotGallery from "./MascotGallery";
it("previews every supplied state, changes size and disables motion", () => {
  render(<MascotGallery />);
  expect(screen.getAllByRole("button", { name: /Выбрать:/ })).toHaveLength(40);
  fireEvent.click(
    screen.getByRole("button", { name: "Выбрать: Найден инсайт" }),
  );
  const preview = screen.getByRole("region", { name: "Выбранное состояние" });
  expect(within(preview).getByRole("img")).toHaveAttribute(
    "src",
    "/mascot/insight.svg",
  );
  fireEvent.change(screen.getByLabelText("Размер маскота"), {
    target: { value: "96" },
  });
  expect(within(preview).getByRole("img")).toHaveAttribute("width", "96");
  fireEvent.click(screen.getByRole("checkbox", { name: "Без анимации" }));
  expect(preview.querySelector('[data-motion="off"]')).toBeInTheDocument();
});
