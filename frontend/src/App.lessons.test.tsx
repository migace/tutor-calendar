import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Lesson, ManagedBooking, Profile, Series, Week } from "./api/client";
import { App } from "./App";
import { json, mockApi } from "./test/mockApi";

const PROFILE: Profile = {
  slug: "demo",
  display_name: "Demo Tutor",
  email: "demo@example.com",
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
};
const signedIn = () => json(200, PROFILE);

// Fixed "now": Monday 16 November 2026, 09:00 in Warsaw.
const NOW = new Date("2026-11-16T08:00:00Z");

function lesson(changes: Partial<Lesson> = {}): Lesson {
  return {
    id: "0b5c1f4e-0000-4000-8000-000000000001",
    start: "2026-11-17T14:00:00Z",
    end: "2026-11-17T15:00:00Z",
    student_name: "Anna Nowak",
    student_email: "anna@example.com",
    status: "confirmed",
    cancelled_by: null,
    cancelled_late: null,
    series_id: null,
    ...changes,
  };
}

function week(lessons: Lesson[]): Week {
  return {
    timezone: "Europe/Warsaw",
    today: "2026-11-16",
    previous: "2026-11-09",
    next: "2026-11-23",
    days: Array.from({ length: 7 }, (_, n) => ({
      date: `2026-11-${16 + n}`,
      lessons: lessons.filter((each) => each.start.startsWith(`2026-11-${16 + n}`)),
    })),
  };
}

function managed(changes: Partial<ManagedBooking> = {}): ManagedBooking {
  return {
    tutor_name: "Demo Tutor",
    timezone: "Europe/Warsaw",
    start: "2026-11-17T14:00:00Z",
    end: "2026-11-17T15:00:00Z",
    student_name: "Anna Nowak",
    status: "confirmed",
    cancelled_by: null,
    cancelled_late: null,
    free_cancellation_until: "2026-11-16T14:00:00Z",
    can_cancel: true,
    late_if_cancelled_now: false,
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

function freezeTime() {
  // Only Date is faked: timers keep running, so queries and retries behave normally.
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("managing a booking with its link", () => {
  const TOKEN = "0b5c1f4e000040008000000000000001.signature";

  it("shows the lesson and the cancellation terms, and sends the token in a header", async () => {
    const api = mockApi({ "GET /api/v1/booking": () => json(200, managed()) });

    renderApp("/booking", `#token=${TOKEN}`);

    expect(await screen.findByRole("heading", { name: "Demo Tutor" })).toBeVisible();
    expect(screen.getByText(/Tuesday 17 November/)).toBeVisible();
    expect(screen.getByText(/You can cancel free of charge until Monday 16 November/)).toBeVisible();
    expect(api.calls[0]!.url).toBe("/api/v1/booking");
    const headers = new Headers(
      (vi.mocked(fetch).mock.calls[0]![1] as RequestInit | undefined)?.headers,
    );
    expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
  });

  it("asks before cancelling, and backing out changes nothing", async () => {
    const api = mockApi({ "GET /api/v1/booking": () => json(200, managed()) });
    const user = renderApp("/booking", `#token=${TOKEN}`);

    await user.click(await screen.findByRole("button", { name: "Cancel lesson" }));

    const question = screen.getByRole("group", { name: "Cancel this lesson?" });
    expect(within(question).getByRole("button", { name: "No, keep it" })).toHaveFocus();

    await user.click(within(question).getByRole("button", { name: "No, keep it" }));

    expect(screen.getByRole("button", { name: "Cancel lesson" })).toHaveFocus();
    expect(api.callsTo("DELETE /api/v1/booking")).toHaveLength(0);
  });

  it("cancels and says the lesson will not be charged", async () => {
    const api = mockApi({
      "GET /api/v1/booking": () => json(200, managed()),
      "DELETE /api/v1/booking": () =>
        json(
          200,
          managed({
            status: "cancelled",
            cancelled_by: "student",
            cancelled_late: false,
            can_cancel: false,
          }),
        ),
    });
    const user = renderApp("/booking", `#token=${TOKEN}`);

    await user.click(await screen.findByRole("button", { name: "Cancel lesson" }));
    await user.click(screen.getByRole("button", { name: "Yes, cancel" }));

    const heading = await screen.findByRole("heading", { name: "This lesson is cancelled" });
    expect(heading).toHaveFocus();
    expect(screen.getByText(/will not be charged/)).toBeVisible();
    expect(api.callsTo("DELETE /api/v1/booking")).toHaveLength(1);
  });

  it("warns before a late cancellation that the lesson is still charged", async () => {
    mockApi({
      "GET /api/v1/booking": () => json(200, managed({ late_if_cancelled_now: true })),
    });
    const user = renderApp("/booking", `#token=${TOKEN}`);

    expect(await screen.findByText(/free of charge has passed/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Cancel lesson" }));

    expect(
      screen.getByRole("group", { name: "Cancel this lesson? It will still be charged." }),
    ).toBeVisible();
  });

  it("offers no cancelling once the lesson has started", async () => {
    mockApi({ "GET /api/v1/booking": () => json(200, managed({ can_cancel: false })) });

    renderApp("/booking", `#token=${TOKEN}`);

    expect(await screen.findByText(/can no longer be cancelled here/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Cancel lesson" })).toBeNull();
  });

  it.each([
    ["a link the server does not recognise", `#token=${TOKEN}`],
    ["a link without a token", ""],
  ])("explains %s", async (_, hash) => {
    mockApi({ "GET /api/v1/booking": () => json(401, { detail: "this link is not valid" }) });

    renderApp("/booking", hash);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This link does not lead to a booking",
    );
  });
});

describe("a tutor's lessons in the week", () => {
  function openWeek(lessons: Lesson[], change?: () => Response) {
    const weeks = [week(lessons)];
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/week": () => json(200, weeks[0]),
      "POST /api/v1/me/lessons/0b5c1f4e-0000-4000-8000-000000000001/cancellation": () => {
        const reply = change?.() ?? json(200, lesson({ status: "cancelled", cancelled_by: "tutor" }));
        if (reply.ok) weeks[0] = week([lesson({ status: "cancelled", cancelled_by: "tutor", cancelled_late: false })]);
        return reply;
      },
      "POST /api/v1/me/lessons/0b5c1f4e-0000-4000-8000-000000000001/no-show": () =>
        json(200, lesson({ status: "no_show" })),
    });
    freezeTime();
    return { api, user: renderApp("/panel") };
  }

  it("cancels an upcoming lesson after asking, and shows it as cancelled", async () => {
    const { api, user } = openWeek([lesson()]);

    const tuesday = await screen.findByRole("listitem", { name: /Tuesday 17 Nov/ });
    await user.click(within(tuesday).getByRole("button", { name: "Cancel" }));
    await user.click(within(tuesday).getByRole("button", { name: "Yes, cancel" }));

    expect(await within(tuesday).findByText("Cancelled by you")).toBeVisible();
    expect(within(tuesday).queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("No lessons");
    expect(
      api.callsTo("POST /api/v1/me/lessons/0b5c1f4e-0000-4000-8000-000000000001/cancellation"),
    ).toHaveLength(1);
  });

  it("offers recording a no-show, not cancelling, for a lesson that has started", async () => {
    const started = lesson({ start: "2026-11-16T07:00:00Z", end: "2026-11-16T08:30:00Z" });
    const { api, user } = openWeek([started]);

    const monday = await screen.findByRole("listitem", { name: /Monday 16 Nov/ });
    expect(within(monday).queryByRole("button", { name: "Cancel" })).toBeNull();
    await user.click(within(monday).getByRole("button", { name: "No-show" }));
    await user.click(within(monday).getByRole("button", { name: "Yes, no-show" }));

    await waitFor(() =>
      expect(
        api.callsTo("POST /api/v1/me/lessons/0b5c1f4e-0000-4000-8000-000000000001/no-show"),
      ).toHaveLength(1),
    );
  });

  it("marks weekly lessons and describes how a lesson was cancelled", async () => {
    openWeek([
      lesson({ series_id: "5e71e5b0-0000-4000-8000-000000000000" }),
      lesson({
        id: "0b5c1f4e-0000-4000-8000-000000000002",
        start: "2026-11-18T14:00:00Z",
        end: "2026-11-18T15:00:00Z",
        status: "cancelled",
        cancelled_by: "student",
        cancelled_late: true,
      }),
    ]);

    expect(await screen.findByText("Weekly")).toBeVisible();
    expect(screen.getByText("Cancelled late by the student")).toBeVisible();
    // A cancelled lesson is shown but not counted.
    expect(screen.getByRole("status")).toHaveTextContent("1 lesson ·");
  });

  it("says why when the server refuses a change", async () => {
    const { user } = openWeek([lesson()], () =>
      json(409, { detail: "a cancelled lesson cannot be cancelled" }),
    );

    const tuesday = await screen.findByRole("listitem", { name: /Tuesday 17 Nov/ });
    await user.click(within(tuesday).getByRole("button", { name: "Cancel" }));
    await user.click(within(tuesday).getByRole("button", { name: "Yes, cancel" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That was not possible: a cancelled lesson cannot be cancelled.",
    );
  });
});

describe("regular lessons", () => {
  const SERIES: Series = {
    id: "5e71e5b0-0000-4000-8000-000000000000",
    student_name: "Anna Nowak",
    student_email: "anna@example.com",
    first_day: "2026-11-17",
    start: "17:00:00",
    weeks: 3,
    days_without_lesson: ["2026-11-24"],
    lessons: [
      lesson({ id: "a", start: "2026-11-17T16:00:00Z", end: "2026-11-17T17:00:00Z" }),
      lesson({ id: "b", start: "2026-12-01T16:00:00Z", end: "2026-12-01T17:00:00Z" }),
    ],
  };

  function openRegulars(existing: Series[], replies: (() => Response)[] = []) {
    const api = mockApi({
      "GET /api/v1/me": signedIn,
      "GET /api/v1/me/series": () => json(200, existing),
      ...Object.fromEntries(
        // The client makes up the id, so any series address is answered.
        [] as [string, () => Response][],
      ),
    });
    // PUT and DELETE go to an address containing an id the test cannot know in advance.
    const base = vi.mocked(fetch).getMockImplementation()!;
    const queue = [...replies];
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/api/v1/me/series/") && init?.method) {
        api.calls.push({ method: init.method, url, body: init.body ? JSON.parse(String(init.body)) : null });
        return (queue.length > 1 ? queue.shift()! : queue[0]!)();
      }
      return base(input, init);
    });
    freezeTime();
    return { api, user: renderApp("/panel/regulars") };
  }

  async function fillIn(user: ReturnType<typeof userEvent.setup>) {
    await user.type(await screen.findByLabelText("Student's name"), "Anna Nowak");
    await user.type(screen.getByLabelText("Student's email"), "anna@example.com");
    fireEvent.change(screen.getByLabelText("First lesson"), { target: { value: "2026-11-17" } });
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "17:00" } });
    await user.clear(screen.getByLabelText("Number of weeks"));
    await user.type(screen.getByLabelText("Number of weeks"), "3");
  }

  it("lists each series with what is left of it", async () => {
    openRegulars([SERIES]);

    const item = (await screen.findByRole("heading", { name: "Anna Nowak · Tuesdays at 17:00" }))
      .parentElement!;
    expect(item).toHaveTextContent("2 still to come, next on 17 November.");
    expect(item).toHaveTextContent("No lesson on 24 November.");
  });

  it("books a series under an id the page chose", async () => {
    const { api, user } = openRegulars([], [() => json(200, SERIES)]);

    await fillIn(user);
    await user.click(screen.getByRole("button", { name: "Book these lessons" }));

    expect(await screen.findByText("Booked 2 lessons for Anna Nowak.")).toBeVisible();
    const [put] = api.calls.filter((call) => call.method === "PUT");
    expect(put!.url).toMatch(/^\/api\/v1\/me\/series\/[0-9a-f-]{36}$/);
    expect(put!.body).toEqual({
      student_name: "Anna Nowak",
      student_email: "anna@example.com",
      first_day: "2026-11-17",
      start: "17:00",
      weeks: 3,
      skip_conflicts: false,
    });
  });

  it("shows the clashing days and can book the rest, as the same series", async () => {
    const clash = () =>
      json(409, { detail: "some of these lessons overlap", conflicts: ["2026-11-24"] });
    const { api, user } = openRegulars([], [clash, () => json(200, SERIES)]);

    await fillIn(user);
    await user.click(screen.getByRole("button", { name: "Book these lessons" }));

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("There is already a lesson on 24 November.");
    expect(warning).toHaveTextContent("Nothing has been booked yet.");

    await user.click(within(warning).getByRole("button", { name: "Book the other weeks" }));

    expect(await screen.findByText("Booked 2 lessons for Anna Nowak.")).toBeVisible();
    const puts = api.calls.filter((call) => call.method === "PUT");
    expect(puts.map((call) => (call.body as { skip_conflicts: boolean }).skip_conflicts)).toEqual([
      false,
      true,
    ]);
    expect(puts[1]!.url).toBe(puts[0]!.url);
  });

  it("points out what is missing before sending anything", async () => {
    const { api, user } = openRegulars([]);

    await user.click(await screen.findByRole("button", { name: "Book these lessons" }));

    expect(screen.getByLabelText("Student's name")).toHaveFocus();
    expect(screen.getByLabelText("First lesson")).toBeInvalid();
    expect(api.calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  });

  it("ends a series after asking", async () => {
    const ended = { ...SERIES, lessons: SERIES.lessons.map((l) => ({ ...l, status: "cancelled" })) };
    const { api, user } = openRegulars([SERIES], [() => json(200, ended)]);

    await user.click(await screen.findByRole("button", { name: "End series" }));
    expect(
      screen.getByRole("group", {
        name: "Cancel the 2 lessons still to come? The student is not charged.",
      }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Yes, end it" }));

    await waitFor(() =>
      expect(api.calls.filter((call) => call.method === "DELETE").map((call) => call.url)).toEqual(
        [`/api/v1/me/series/${SERIES.id}`],
      ),
    );
  });
});
