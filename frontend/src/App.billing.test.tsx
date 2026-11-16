import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Account, LedgerEntry, Profile, Statement } from "./api/client";
import { App } from "./App";
import { formatMinutes } from "./dates";
import { json, mockApi } from "./test/mockApi";

const PROFILE: Profile = {
  slug: "demo",
  display_name: "Demo Tutor",
  email: "demo@example.com",
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
};
const signedIn = () => json(200, PROFILE);

const PACKAGE: LedgerEntry = {
  id: "11111111-0000-4000-8000-000000000001",
  kind: "purchase",
  minutes: 600,
  note: "Package of 10",
  at: "2026-11-02T09:00:00Z",
  lesson_id: null,
};
const LESSON: LedgerEntry = {
  id: "11111111-0000-4000-8000-000000000002",
  kind: "lesson",
  minutes: -60,
  note: "Lesson",
  // 23:30 UTC on the 17th is the 18th in Warsaw, the tutor's zone.
  at: "2026-11-17T23:30:00Z",
  lesson_id: "22222222-0000-4000-8000-000000000001",
};

function statement(changes: Partial<Statement> = {}): Statement {
  return {
    tutor_name: "Demo Tutor",
    timezone: "Europe/Warsaw",
    student_email: "anna@example.com",
    student_name: "Anna Nowak",
    month: "2026-11-01",
    previous: "2026-10-01",
    next: "2026-12-01",
    opening_minutes: 30,
    closing_minutes: 570,
    balance_minutes: 570,
    entries: [PACKAGE, LESSON],
    share_token: "c2hhcmU.signature",
    ...changes,
  };
}

function renderApp(path: string, hash = "") {
  window.history.replaceState(null, "", `${path}${hash}`);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retryDelay: 0 } },
  });
  render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
  return userEvent.setup();
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("formatMinutes", () => {
  it.each([
    [600, "10 h"],
    [90, "1 h 30 min"],
    [45, "45 min"],
    [0, "0 min"],
    [-60, "−1 h"],
    [-75, "−1 h 15 min"],
  ])("writes %i minutes as %s", (minutes, text) => {
    expect(formatMinutes(minutes)).toBe(text);
  });
});

describe("students", () => {
  it("lists each student with the time they have left, or owe", async () => {
    const accounts: Account[] = [
      { email: "anna@example.com", name: "Anna Nowak", balance_minutes: 570 },
      { email: "bartek@example.com", name: null, balance_minutes: -60 },
    ];
    mockApi({ "GET /api/v1/me": signedIn, "GET /api/v1/me/students": () => json(200, accounts) });

    renderApp("/panel/students");

    const anna = (await screen.findByRole("link", { name: "Anna Nowak" })).closest("li")!;
    expect(anna).toHaveTextContent("9 h 30 min left");
    expect(within(anna).getByRole("link")).toHaveAttribute(
      "href",
      "/panel/students/anna%40example.com",
    );
    // Without a name, the address stands in for it.
    const bartek = screen.getByRole("link", { name: "bartek@example.com" }).closest("li")!;
    expect(bartek).toHaveTextContent("1 h to pay for");
    expect(screen.getByRole("link", { name: "Students" })).toHaveAttribute("aria-current", "page");
  });
});

describe("a student's account", () => {
  function openAccount(replies: (() => Response | Promise<Response>)[] = []) {
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/students/anna%40example.com/statement": (call) =>
        json(
          200,
          call.url.includes("month=2026-12-01")
            ? statement({ month: "2026-12-01", previous: "2026-11-01", next: "2027-01-01", opening_minutes: 570, entries: [] })
            : statement(),
        ),
    });
    // The id of an entry is made up by the page, so its address cannot be listed in advance.
    const base = vi.mocked(fetch).getMockImplementation()!;
    const queue = [...replies];
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "PUT" && url.includes("/entries/")) {
        api.calls.push({ method: "PUT", url, body: JSON.parse(String(init.body)) });
        return (queue.length > 1 ? queue.shift()! : queue[0]!)();
      }
      return base(input, init);
    });
    const puts = () => api.calls.filter((call) => call.method === "PUT");
    return { api, puts, user: renderApp("/panel/students/anna%40example.com") };
  }

  it("shows the month as a statement: opening balance, entries, closing balance", async () => {
    openAccount();

    const table = await screen.findByRole("table", { name: /Lesson time in November 2026/ });
    const rows = within(table)
      .getAllByRole("row")
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "DateWhatTime",
      "Balance at the start of the month30 min",
      "2 NovPackage of 10+10 h",
      // The lesson is dated on the tutor's calendar, where it was already the 18th.
      "18 NovLesson−1 h",
      "Balance at the end of the month9 h 30 min",
    ]);
    expect(screen.getByRole("heading", { name: "Anna Nowak" })).toBeVisible();
    expect(screen.getByText("9 h 30 min left")).toBeVisible();
  });

  it("moves between months", async () => {
    const { user } = openAccount();

    await user.click(await screen.findByRole("link", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "December 2026" })).toBeVisible();
    expect(screen.getByText("Nothing happened this month.")).toBeVisible();
  });

  it("records a package in minutes, under an id the page chose", async () => {
    const { puts, user } = openAccount([() => json(200, PACKAGE)]);

    await user.type(await screen.findByLabelText("Hours"), "7,5");
    await user.type(screen.getByLabelText("Note (optional)"), " Package of 10 ");
    await user.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByText("Recorded +10 h.")).toBeVisible();
    expect(puts()).toHaveLength(1);
    expect(puts()[0]!.url).toMatch(
      /^\/api\/v1\/me\/students\/anna%40example\.com\/entries\/[0-9a-f-]{36}$/,
    );
    expect(puts()[0]!.body).toEqual({ kind: "purchase", minutes: 450, note: "Package of 10" });
    expect(screen.getByLabelText("Hours")).toHaveValue("");
  });

  it("repeats a failed request under the same id, and gives the next package a new one", async () => {
    const down = () => Promise.reject(new TypeError("Failed to fetch"));
    const { puts, user } = openAccount([down, () => json(200, PACKAGE), () => json(200, PACKAGE)]);

    await user.type(await screen.findByLabelText("Hours"), "10");
    await user.click(screen.getByRole("button", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("it is safe to try again");
    await user.click(screen.getByRole("button", { name: "Record" }));
    expect(await screen.findByText("Recorded +10 h.")).toBeVisible();

    // A second package of the same size is a different entry, not a repeat.
    await user.type(screen.getByLabelText("Hours"), "10");
    await user.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() => expect(puts()).toHaveLength(3));

    const [failed, retried, second] = puts().map((call) => call.url);
    expect(retried).toBe(failed);
    expect(second).not.toBe(failed);
  });

  it("asks for a reason before recording a correction", async () => {
    const { puts, user } = openAccount([() => json(200, { ...PACKAGE, minutes: -60 })]);

    await user.click(await screen.findByRole("radio", { name: "A correction" }));
    await user.type(screen.getByLabelText("Hours"), "-1");
    await user.click(screen.getByRole("button", { name: "Record" }));

    const reason = screen.getByLabelText("Reason");
    expect(reason).toBeInvalid();
    expect(reason).toHaveFocus();
    expect(puts()).toHaveLength(0);

    await user.type(reason, "Lesson was cut short");
    await user.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]!.body).toEqual({
      kind: "adjustment",
      minutes: -60,
      note: "Lesson was cut short",
    });
  });

  it.each([
    ["", /Enter a number of hours/],
    ["ten", /Enter a number of hours/],
    ["-2", /A package adds time/],
  ])("does not send %j as a package", async (typed, message) => {
    const { puts, user } = openAccount();

    if (typed) await user.type(await screen.findByLabelText("Hours"), typed);
    await user.click(await screen.findByRole("button", { name: "Record" }));

    expect(screen.getByLabelText("Hours")).toHaveAccessibleDescription(message);
    expect(puts()).toHaveLength(0);
  });

  it("offers a link the parent can open", async () => {
    openAccount();

    expect(await screen.findByRole("link", { name: "Open the parent’s view" })).toHaveAttribute(
      "href",
      "/statement#token=c2hhcmU.signature",
    );
  });

  it("lets the tutor open an account for someone who has not booked yet", async () => {
    mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/students": () => json(200, []),
      "GET /api/v1/me/students/new%40example.com/statement": () =>
        json(404, { detail: "no such statement" }),
    });
    const user = renderApp("/panel/students");

    await user.type(await screen.findByLabelText("Find or add a student by email"), "New@Example.com");
    await user.click(screen.getByRole("button", { name: "Open account" }));

    expect(await screen.findByRole("heading", { name: "new@example.com" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Nothing is recorded for this address yet" }),
    ).toBeVisible();
    // The form that records time is there, which is what opens the account.
    expect(screen.getByRole("button", { name: "Record" })).toBeVisible();
  });

  it("does not go looking for something that is not an address", async () => {
    mockApi({ "GET /api/v1/me": signedIn, "GET /api/v1/me/students": () => json(200, []) });
    const user = renderApp("/panel/students");

    await user.type(await screen.findByLabelText("Find or add a student by email"), "anna");
    await user.click(screen.getByRole("button", { name: "Open account" }));

    expect(screen.getByLabelText("Find or add a student by email")).toBeInvalid();
    expect(screen.getByRole("heading", { name: "Students" })).toBeVisible();
  });
});

describe("the parent's view", () => {
  const TOKEN = "c2hhcmU.signature";

  it("shows the statement, sending the token in a header and keeping it out of the query", async () => {
    const api = mockApi({
      "GET /api/v1/statement": () => json(200, statement({ share_token: null })),
    });

    renderApp("/statement", `#token=${TOKEN}`);

    expect(await screen.findByRole("heading", { name: "Anna Nowak" })).toBeVisible();
    expect(screen.getByText(/Lessons with Demo Tutor/)).toBeVisible();
    expect(screen.getByRole("table")).toBeVisible();
    expect(api.calls[0]!.url).toBe("/api/v1/statement");
    const headers = new Headers(
      (vi.mocked(fetch).mock.calls[0]![1] as RequestInit | undefined)?.headers,
    );
    expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    // Nothing a parent could use to change the account, or to share further.
    expect(screen.queryByRole("button", { name: "Record" })).toBeNull();
    expect(screen.queryByRole("link", { name: /parent/ })).toBeNull();
  });

  it("keeps the token when moving to another month", async () => {
    const api = mockApi({
      "GET /api/v1/statement": (call) =>
        json(
          200,
          statement({
            share_token: null,
            ...(call.url.includes("2026-10-01") ? { month: "2026-10-01", entries: [] } : {}),
          }),
        ),
    });
    const user = renderApp("/statement", `#token=${TOKEN}`);

    const previous = await screen.findByRole("link", { name: "Previous" });
    expect(previous).toHaveAttribute("href", `/statement?month=2026-10-01#token=${TOKEN}`);
    await user.click(previous);

    expect(await screen.findByRole("heading", { name: "October 2026" })).toBeVisible();
    expect(api.calls.at(-1)!.url).toBe("/api/v1/statement?month=2026-10-01");
  });

  it.each([
    ["a link the server does not recognise", `#token=${TOKEN}`],
    ["a link without a token", ""],
  ])("explains %s", async (_, hash) => {
    mockApi({ "GET /api/v1/statement": () => json(401, { detail: "this link is not valid" }) });

    renderApp("/statement", hash);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This link does not lead to a statement",
    );
  });
});
