import { render, screen } from "@testing-library/react";
import { GeneratedDashboard } from "./GeneratedDashboard";

it.each([true, false, undefined])("discloses the actual line limit flag %s without inventing extra groups", (limitReached) => {
  render(<GeneratedDashboard scope="limit-test" dashboard={{ version: 1, title: "Панель", cards: [{
    id: "line-1", type: "line", title: "Значения", status: "success",
    data: { points: [{ x: "A", y: 10 }, { x: "B", y: 20 }], limit: 2, limit_reached: limitReached },
  }] }} />);
  if (limitReached) {
    expect(screen.getByText(/Показано точек: 2. Достигнут лимит выдачи/)).toBeInTheDocument();
    expect(screen.getByText(/могут быть другие группы/)).toBeInTheDocument();
  } else expect(screen.queryByText(/Достигнут лимит/)).not.toBeInTheDocument();
});
