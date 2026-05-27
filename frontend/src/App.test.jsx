import { render, screen } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the main page heading", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /Agent Orchestration Platform/i,
      })
    ).toBeInTheDocument();
  });

  it("renders the create agent section", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /Create Agent/i,
      })
    ).toBeInTheDocument();
  });

  it("renders the run demo workflow section", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /Run Demo Workflow/i,
      })
    ).toBeInTheDocument();
  });

  it("renders the workflow runs section", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /Workflow Runs/i,
      })
    ).toBeInTheDocument();
  });
});