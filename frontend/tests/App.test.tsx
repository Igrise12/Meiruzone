import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { fixtureAdapter, type InboxAdapter } from "../src/api";
import { sampleEmails } from "../src/data";
import { categoryStats } from "../src/treemap";

function adapter(overrides: Partial<InboxAdapter> = {}): InboxAdapter {
  const getEmails = overrides.getEmails ?? fixtureAdapter.getEmails;
  const getLabels = overrides.getLabels ?? fixtureAdapter.getLabels;
  return {
    ...fixtureAdapter,
    ...overrides,
    getCategoryStats: overrides.getCategoryStats ?? (async () => categoryStats(await getEmails(), await getLabels())),
  };
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("Smart Inbox", () => {
  it("filters from a treemap category while the map stays on full mailbox totals", async () => {
    render(<App />);
    await screen.findByText("A note for Rowan");
    const categoryList = screen.getByLabelText("Category counts");
    fireEvent.click(within(categoryList).getByRole("button", { name: /Recruitment/ }));

    expect(screen.getByRole("button", { name: /Jo Park.*Product designer interview/ })).toBeInTheDocument();
    expect(screen.queryByText("A new message from Avery Chen")).not.toBeInTheDocument();
    expect(screen.getByText("Full sample mailbox · independent of inbox filters")).toBeInTheDocument();
    expect(within(categoryList).getByRole("button", { name: /Recruitment/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("supports search, Needs Review, and keyboard-operable native buttons", async () => {
    render(<App />);
    await screen.findByText("A note for Rowan");
    const search = screen.getByRole("searchbox", { name: "Search messages" });
    fireEvent.change(search, { target: { value: "Northstar" } });
    expect(screen.getByRole("button", { name: /Jo Park.*Product designer interview/ })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Filter messages" })).getByRole("button", { name: /Needs review/ }));
    expect(screen.getByRole("button", { name: /Jo Park.*Product designer interview/ })).toBeInTheDocument();
    expect(within(screen.getByLabelText("Email message list")).queryByText("A saved note without a prediction")).not.toBeInTheDocument();
    const reviewButton = screen.getByRole("button", { name: /Jo Park.*Product designer interview/ });
    expect(reviewButton).toHaveAttribute("type", "button");
    expect(reviewButton.tabIndex).toBe(0);
    fireEvent.change(screen.getByLabelText("Filter by priority"), { target: { value: "High" } });
    expect(screen.getByText("2 messages", { selector: "#result-count" })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "no matching message" } });
    expect(screen.getByText("No messages here")).toBeInTheDocument();
  });

  it("saves human corrections separately from the prediction", async () => {
    render(<App />);
    await screen.findByText("A note for Rowan");
    fireEvent.click(screen.getByRole("button", { name: /Jo Park/ }));
    fireEvent.change(within(screen.getByRole("article", { name: "Selected email" })).getByLabelText("Category"), { target: { value: "Personal" } });
    fireEvent.change(within(screen.getByRole("article", { name: "Selected email" })).getByLabelText("Priority"), { target: { value: "Low" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Your labels are saved on this device.");

    expect(screen.getByText("Human label · saved on this device")).toBeInTheDocument();
    expect(screen.getByText("Recruitment", { selector: ".prediction-values .tag" })).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByLabelText("Category counts")).getByRole("button", { name: /Personal 5/ })).toBeInTheDocument());
  });

  it("keeps the selected correction visible after a save failure", async () => {
    const saveLabel = vi.fn().mockRejectedValue(new Error("Storage unavailable"));
    render(<App adapter={adapter({ saveLabel })} />);
    await screen.findByText("A note for Rowan");
    fireEvent.click(screen.getByRole("button", { name: /Jo Park/ }));
    fireEvent.change(within(screen.getByRole("article", { name: "Selected email" })).getByLabelText("Category"), { target: { value: "Personal" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));

    await screen.findByText("Labels could not be saved. Your changes are still here—try again.");
    expect(within(screen.getByRole("article", { name: "Selected email" })).getByLabelText("Category")).toHaveValue("Personal");
  });

  it("offers a sync retry after mocked sync failure", async () => {
    const sync = vi.fn().mockRejectedValue(new Error("offline"));
    render(<App adapter={adapter({ sync })} />);
    await screen.findByText("A note for Rowan");
    fireEvent.click(screen.getByRole("button", { name: "Sync sample" }));
    await screen.findByRole("alert");
    expect(screen.getByText("Sync did not finish. Check the connection and try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders message markup as text rather than as executable HTML", async () => {
    const unsafe = { ...sampleEmails[0], id: "unsafe", subject: "Literal markup", body: '<img src="https://tracker.invalid/pixel" onerror="alert(1)">' };
    render(<App adapter={adapter({ getEmails: async () => [unsafe], getLabels: async () => ({}) })} />);
    fireEvent.click(await screen.findByRole("button", { name: /Jo Park.*Literal markup/ }));

    expect(within(screen.getByRole("article", { name: "Selected email" })).getByText('<img src="https://tracker.invalid/pixel" onerror="alert(1)">')).toBeInTheDocument();
    expect(document.querySelector(".detail-body img")).toBeNull();
  });

  it("shows an explicit empty inbox state", async () => {
    render(<App adapter={adapter({ getEmails: async () => [], getLabels: async () => ({}) })} />);
    await waitFor(() => expect(screen.getByText("Your inbox is empty")).toBeInTheDocument());
    expect(screen.getByText("No messages yet. Sync to load the local inbox.")).toBeInTheDocument();
  });

  it("keeps mailbox data available while dashboard aggregates load", async () => {
    render(<App adapter={adapter({ getCategoryStats: () => new Promise(() => {}) })} />);
    expect(screen.getByText("Loading category counts…")).toBeInTheDocument();
    expect(await screen.findByText("A note for Rowan")).toBeInTheDocument();
    expect(screen.getByText("18 messages", { selector: "#result-count" })).toBeInTheDocument();
  });

  it("shows an aggregate error without hiding loaded inbox messages", async () => {
    render(<App adapter={adapter({ getCategoryStats: async () => { throw new Error("aggregate unavailable"); } })} />);
    expect(await screen.findByText("A note for Rowan")).toBeInTheDocument();
    expect(await screen.findByText("Category counts could not be loaded. Reload the inbox to try again.")).toBeInTheDocument();
    expect(screen.getByText("18 messages", { selector: "#result-count" })).toBeInTheDocument();
  });
});
