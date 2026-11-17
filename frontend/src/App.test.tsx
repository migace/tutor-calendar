import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Availability, Lesson, Profile, Week } from "./api/client";
import { App } from "./App";
import { json, mockApi } from "./test/mockApi";

const PROFILE: Profile = {
  slug: "demo",
  display_name: "Demo Tutor",
  email: "demo@example.com",
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
};

function week(monday: number, lessons: Week["days"][number]["lessons"] = []): Week {
  const date = (day: number) => `2026-11-${String(day).padStart(2, "0")}`;
  return {
    timezone: "Europe/Warsaw",
    today: "2026-11-16",
    previous: date(monday - 7),
    next: date(monday + 7),
    days: Array.from({ length: 7 }, (_, n) => ({
      date: date(monday + n),
      lessons: n === 1 ? lessons : [],
    })),
  };
}

const ANNA: Lesson = {
  id: "0b5c1f4e-0000-4000-8000-000000000001",
  start: "2026-11-17T14:00:00Z",
  end: "2026-11-17T15:00:00Z",
  student_name: "Anna Nowak",
  student_email: "anna@example.com",
  status: "confirmed",
  cancelled_by: null,
  cancelled_late: null,
  series_id: null,
};

const HOURS: Availability = {
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
  rules: [{ weekday: 0, start: "15:00:00", end: "19:00:00" }],
};

const signedOut = () => json(401, { detail: "sign in to continue" });
const signedIn = () => json(200, PROFILE);

function renderApp(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    // StrictMode mounts everything twice, as in development. Anything that must
    // happen exactly once has to survive that.
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

describe("signing in", () => {
  it("sends anyone who is not signed in from the panel to the sign-in page", async () => {
    mockApi({ "GET /api/v1/me": signedOut });

    renderApp("/panel/availability");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("asks for a link and says where to look, without revealing whether the address is known", async () => {
    const api = mockApi({
      "GET /api/v1/me": signedOut,
      "POST /api/v1/auth/links": () => json(202, null),
    });
    const user = renderApp("/sign-in");

    await user.type(await screen.findByLabelText("Email address"), "  demo@example.com ");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    const heading = await screen.findByRole("heading", { name: "Check your email" });
    expect(heading).toHaveFocus();
    expect(screen.getByText(/belongs to a tutor/)).toHaveTextContent("demo@example.com");
    expect(api.callsTo("POST /api/v1/auth/links").map((call) => call.body)).toEqual([
      { email: "demo@example.com" },
    ]);
  });

  it("says to wait, not to try again, when the server's request limit is reached", async () => {
    const api = mockApi({
      "GET /api/v1/me": signedOut,
      "POST /api/v1/auth/links": () => json(429, { detail: "too many requests, try again later" }),
    });
    const user = renderApp("/sign-in");

    await user.type(await screen.findByLabelText("Email address"), "demo@example.com");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts from your network. Wait a few minutes and try again.",
    );
    // Asked once: repeating a refused request would only use up more of the allowance.
    expect(api.callsTo("POST /api/v1/auth/links")).toHaveLength(1);
  });

  it("catches a mistyped address before sending anything", async () => {
    const api = mockApi({ "GET /api/v1/me": signedOut });
    const user = renderApp("/sign-in");

    await user.type(await screen.findByLabelText("Email address"), "demo@");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    const input = screen.getByLabelText("Email address");
    expect(input).toBeInvalid();
    expect(input).toHaveFocus();
    expect(api.callsTo("POST /api/v1/auth/links")).toHaveLength(0);
  });

  it("uses the token from the link exactly once and opens the panel", async () => {
    window.history.replaceState(null, "", "/sign-in/verify#token=the-token-from-the-email");
    const api = mockApi({
      "POST /api/v1/auth/session": signedIn,
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/week": () => json(200, week(16)),
    });

    renderApp("/sign-in/verify");

    expect(await screen.findByRole("heading", { name: "16 – 22 November 2026" })).toBeVisible();
    expect(api.callsTo("POST /api/v1/auth/session").map((call) => call.body)).toEqual([
      { token: "the-token-from-the-email" },
    ]);
    // The token does not linger in the address bar or the history.
    expect(window.location.hash).toBe("");
  });

  it("explains a link that no longer works and offers a new one", async () => {
    window.history.replaceState(null, "", "/sign-in/verify#token=an-old-token-used-before");
    mockApi({
      "POST /api/v1/auth/session": () => json(401, { detail: "this sign-in link is not valid" }),
      "GET /api/v1/me": signedOut,
    });
    const user = renderApp("/sign-in/verify");

    expect(await screen.findByRole("alert")).toHaveTextContent("does not work any more");

    await user.click(screen.getByRole("link", { name: "Email me a new link" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("treats a link without a token as one that does not work", async () => {
    const api = mockApi({});

    renderApp("/sign-in/verify");

    expect(await screen.findByRole("alert")).toHaveTextContent("does not work any more");
    expect(api.callsTo("POST /api/v1/auth/session")).toHaveLength(0);
  });

  it("signs out and forgets what was loaded", async () => {
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/week": () => json(200, week(16, [ANNA])),
      "DELETE /api/v1/auth/session": () => json(204, null),
    });
    const user = renderApp("/panel");

    await user.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("Anna Nowak")).toBeNull();
    expect(api.callsTo("DELETE /api/v1/auth/session")).toHaveLength(1);
  });
});

describe("the week", () => {
  it("shows lessons on their day, in the tutor's time zone", async () => {
    mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/week": () => json(200, week(16, [ANNA])),
    });

    renderApp("/panel");

    const tuesday = await screen.findByRole("listitem", { name: /Tuesday 17 Nov/ });
    expect(within(tuesday).getByText("15:00–16:00")).toBeInTheDocument();
    expect(within(tuesday).getByRole("link", { name: "anna@example.com" })).toHaveAttribute(
      "href",
      "mailto:anna@example.com",
    );
    expect(screen.getByRole("listitem", { name: /Monday 16 Nov/ })).toHaveAttribute(
      "aria-current",
      "date",
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 lesson");
    expect(screen.getByRole("link", { name: "Week" })).toHaveAttribute("aria-current", "page");
  });

  it("moves to the next week and offers a way back to this one", async () => {
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/week": (call) =>
        json(200, call.url.includes("date=2026-11-23") ? week(23) : week(16, [ANNA])),
    });
    const user = renderApp("/panel");

    expect(screen.queryByRole("link", { name: "This week" })).toBeNull();
    await user.click(await screen.findByRole("link", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "23 – 29 November 2026" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("No lessons");
    expect(api.calls.at(-1)!.url).toBe("/api/v1/me/week?date=2026-11-23");

    await user.click(screen.getByRole("link", { name: "This week" }));
    expect(await screen.findByText("Anna Nowak")).toBeVisible();
  });
});

describe("weekly hours", () => {
  function openHours(saveReplies = [() => json(200, HOURS)]) {
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/availability": () => json(200, HOURS),
      "PUT /api/v1/me/availability": saveReplies,
    });
    return { api, user: renderApp("/panel/availability") };
  }

  it("shows the current hours and saves what the tutor changes", async () => {
    const { api, user } = openHours();

    expect(await screen.findByLabelText("Monday, from")).toHaveValue("15:00");
    expect(within(screen.getByRole("group", { name: "Tuesday" })).getByText("Not teaching")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Monday, to"), { target: { value: "20:30" } });
    await user.click(screen.getByRole("button", { name: "Add hours on Friday" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Saved. Visitors now see these hours.")).toBeVisible();
    expect(api.callsTo("PUT /api/v1/me/availability").map((call) => call.body)).toEqual([
      {
        rules: [
          { weekday: 0, start: "15:00", end: "20:30" },
          { weekday: 4, start: "09:00", end: "12:00" },
        ],
      },
    ]);
  });

  it("points at overlapping hours and saves nothing until they are fixed", async () => {
    const { api, user } = openHours();

    await user.click(await screen.findByRole("button", { name: "Add hours on Monday" }));
    fireEvent.change(screen.getByLabelText("Monday, hours 2, from"), { target: { value: "18:00" } });
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const second = screen.getByLabelText("Monday, hours 2, from");
    expect(second).toBeInvalid();
    expect(second).toHaveFocus();
    expect(second).toHaveAccessibleDescription("These hours overlap the ones before them.");
    expect(api.callsTo("PUT /api/v1/me/availability")).toHaveLength(0);

    fireEvent.change(second, { target: { value: "19:30" } });
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.callsTo("PUT /api/v1/me/availability")).toHaveLength(1));
  });

  it("removes hours, and stops saying 'saved' once they are edited again", async () => {
    const { api, user } = openHours();

    await user.click(await screen.findByRole("button", { name: "Remove Monday 15:00–19:00" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Saved. Visitors now see these hours.")).toBeVisible();
    expect(api.callsTo("PUT /api/v1/me/availability")[0]!.body).toEqual({ rules: [] });

    await user.click(screen.getByRole("button", { name: "Add hours on Sunday" }));
    expect(screen.queryByText("Saved. Visitors now see these hours.")).toBeNull();
  });

  it("shows the server's reason when it refuses the hours", async () => {
    const { user } = openHours([() => json(422, { detail: "rules overlap on Monday" })]);

    await user.click(await screen.findByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server did not accept these hours: rules overlap on Monday.",
    );
  });
});

describe("routing", () => {
  it("opens the demo tutor's booking page at the root address", async () => {
    mockApi({
      "GET /api/v1/tutors/demo/slots": () =>
        json(200, { tutor: { ...PROFILE, email: undefined }, slots: [] }),
    });

    renderApp("/");

    expect(await screen.findByRole("heading", { name: "Demo Tutor" })).toBeVisible();
  });

  it("says so when an address leads nowhere", () => {
    mockApi({});

    renderApp("/no/such/page");

    expect(screen.getByRole("heading", { name: "There is nothing at this address" })).toBeVisible();
  });
});
