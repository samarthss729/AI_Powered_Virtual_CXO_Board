import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders boardroom brand", () => {
  render(<App />);
  expect(screen.getAllByText(/AI Boardroom/i).length).toBeGreaterThan(0);
});
