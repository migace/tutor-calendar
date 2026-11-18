/**
 * An automated accessibility check of every screen, in the states that matter.
 *
 * axe finds the mechanical failures: a control without a name, a broken ARIA
 * reference, a heading out of order, a table without headers. It cannot judge
 * whether the names make sense or whether the page is pleasant to use with a
 * screen reader. See docs/accessibility.md for what was checked by hand.
 */
import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Lesson, ManagedBooking, Profile, Series, Statement, Week } from "./api/client";
import { App } from "./App";
import { setLanguage } from "./i18n";
import { json, mockApi } from "./test/mockApi";

const PROFILE: Profile = {
  slug: "demo",
  display_name: "Demo Tutor",
  email: "demo@example.com",
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
};
const SLOTS = {
  tutor: { slug: "demo", display_name: "Demo Tutor", timezone: "Europe/Warsaw", lesson_minutes: 60 },
  slots: [
    { start: "2026-11-17T14:00:00Z", end: "2026-11-17T15:00:00Z" },
    { start: "2026-11-17T15:00:00Z", end: "2026-11-17T16:00:00Z" },
    { start: "2026-11-21T08:00:00Z", end: "2026-11-21T09:00:00Z" },
  ],
};
const LESSON: Lesson = {
  id: "0b5c1f4e-0000-4000-8000-000000000001",
  start: "2099-11-17T14:00:00Z",
  end: "2099-11-17T15:00:00Z",
  student_name: "Anna Nowak",
  student_email: "anna@example.com",
  status: "confirmed",
  cancelled_by: null,
  cancelled_late: null,
  series_id: "5e71e5b0-0000-4000-8000-000000000000",
};
const WEEK: Week = {
  timezone: "Europe/Warsaw",
  today: "2099-11-16",
  previous: "2099-11-09",
  next: "2099-11-23",
  days: Array.from({ length: 7 }, (_, n) => ({
    date: `2099-11-${16 + n}`,
    lessons:
      n === 1
        ? [LESSON, { ...LESSON, id: "b", status: "cancelled", cancelled_by: "student", cancelled_late: true }]
        : [],
  })),
};
const SERIES: Series = {
  id: "5e71e5b0-0000-4000-8000-000000000000",
  student_name: "Anna Nowak",
  student_email: "anna@example.com",
  first_day: "2099-11-17",
  start: "17:00:00",
  weeks: 3,
  days_without_lesson: ["2099-11-24"],
  lessons: [LESSON],
};
const STATEMENT: Statement = {
  tutor_name: "Demo Tutor",
  timezone: "Europe/Warsaw",
  student_email: "anna@example.com",
  student_name: "Anna Nowak",
  month: "2026-11-01",
  previous: "2026-10-01",
  next: "2026-12-01",
  opening_minutes: 600,
  closing_minutes: -60,
  balance_minutes: -60,
  nothing_recorded: false,
  share_token: "c2hhcmU.signature",
  entries: [
    { id: "e1", kind: "lesson", minutes: -60, note: "Lesson", at: "2026-11-10T16:00:00Z", lesson_id: "l1" },
    { id: "e2", kind: "adjustment", minutes: -600, note: "Refund", at: "2026-11-12T09:00:00Z", lesson_id: null },
  ],
};
const MANAGED: ManagedBooking = {
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
  late_if_cancelled_now: true,
};

const signedIn = () => json(200, PROFILE);
const TOKEN = "#token=c2hhcmU.signature";

function everything(demo = false) {
  return mockApi({
    "GET /api/v1/config": () => json(200, { demo_mode: demo }),
    "GET /api/v1/me": signedIn,
    "GET /api/v1/tutors/demo/slots": () => json(200, SLOTS),
    "POST /api/v1/tutors/demo/bookings": () =>
      json(201, { id: "b1", manage_token: "c2hhcmU.signature", ...SLOTS.slots[0] }),
    "GET /api/v1/booking": () => json(200, MANAGED),
    "GET /api/v1/me/week": () => json(200, WEEK),
    "GET /api/v1/me/availability": () =>
      json(200, {
        timezone: "Europe/Warsaw",
        lesson_minutes: 60,
        rules: [
          { weekday: 0, start: "09:00:00", end: "12:00:00" },
          { weekday: 0, start: "11:00:00", end: "13:00:00" },
        ],
      }),
    "GET /api/v1/me/series": () => json(200, [SERIES]),
    "GET /api/v1/me/students": () =>
      json(200, [
        { id: "aaaaaaaa-0000-4000-8000-000000000001", email: "anna@example.com", name: "Anna Nowak", balance_minutes: -60 },
        {
          id: "bbbbbbbb-0000-4000-8000-000000000002",
          email: "bartek@example.com",
          name: null,
          balance_minutes: 300,
        },
      ]),
    "GET /api/v1/me/students/aaaaaaaa-0000-4000-8000-000000000001/statement": () => json(200, STATEMENT),
    "GET /api/v1/statement": () => json(200, STATEMENT),
  });
}

function open(path: string, hash = "") {
  window.history.replaceState(null, "", `${path}${hash}`);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

async function violations(): Promise<string[]> {
  const results = await axe.run(document.body, {
    rules: {
      // Needs real layout to measure colours; jsdom has none. Contrast is
      // checked from the design tokens at the end of this file instead.
      "color-contrast": { enabled: false },
    },
  });
  return results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help} (${violation.nodes.map((node) => node.html).join(" | ")})`,
  );
}

afterEach(() => {
  setLanguage("en");
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("no screen has a mechanical accessibility failure", () => {
  it("the booking page, from the list of times to the confirmation", async () => {
    everything(true);
    const user = open("/book/demo");

    await screen.findByRole("heading", { name: "Demo Tutor" });
    expect(await violations()).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Tuesday 17 November, 15:00" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Book lesson" })); // shows both errors
    expect(await violations()).toEqual([]);

    await user.type(screen.getByLabelText("Student's name"), "Anna Nowak");
    await user.type(screen.getByLabelText("Email address"), "anna@example.com");
    await user.click(screen.getByRole("button", { name: "Book lesson" }));
    await screen.findByRole("heading", { name: "You’re booked" });
    expect(await violations()).toEqual([]);
  });

  it("managing a booking, with the question open", async () => {
    everything();
    const user = open("/booking", TOKEN);

    await user.click(await screen.findByRole("button", { name: "Cancel lesson" }));

    expect(await violations()).toEqual([]);
  });

  it("signing in, with an error, on a demonstration", async () => {
    mockApi({
      "GET /api/v1/config": () => json(200, { demo_mode: true }),
      "GET /api/v1/me": () => json(401, {}),
    });
    const user = open("/sign-in");

    await user.click(await screen.findByRole("button", { name: "Email me a sign-in link" }));

    expect(screen.getByLabelText("Email address")).toBeInvalid();
    expect(await violations()).toEqual([]);
  });

  it("the week, with a lesson being cancelled", async () => {
    everything();
    const user = open("/panel");

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await violations()).toEqual([]);
  });

  it("weekly hours, with overlapping hours pointed out", async () => {
    everything();
    const user = open("/panel/availability");

    await user.click(await screen.findByRole("button", { name: "Save changes" }));

    expect(screen.getByLabelText("Monday, hours 2, from")).toBeInvalid();
    expect(await violations()).toEqual([]);
  });

  it("regular lessons, with the form's errors showing", async () => {
    everything();
    const user = open("/panel/regulars");

    await user.click(await screen.findByRole("button", { name: "Book these lessons" }));

    expect(await violations()).toEqual([]);
  });

  it("the list of students and one student's account", async () => {
    everything();
    open("/panel/students");
    await screen.findByRole("link", { name: "Anna Nowak" });
    expect(await violations()).toEqual([]);
  });

  it("a student's account with its statement and form", async () => {
    everything();
    const user = open("/panel/students/aaaaaaaa-0000-4000-8000-000000000001");

    await user.click(await screen.findByRole("radio", { name: "A correction" }));
    await user.click(screen.getByRole("button", { name: "Record" }));

    expect(await violations()).toEqual([]);
  });

  it("the parent's view, in Polish", async () => {
    everything();
    setLanguage("pl");
    open("/statement", TOKEN);

    await screen.findByRole("table");

    expect(document.documentElement.lang).toBe("pl");
    expect(await violations()).toEqual([]);
  });

  it("pages that only say something went wrong", async () => {
    mockApi({ "GET /api/v1/booking": () => json(401, {}) });
    open("/booking", TOKEN);
    await screen.findByRole("alert");
    expect(await violations()).toEqual([]);
  });

  it("an address that leads nowhere", async () => {
    mockApi({});
    open("/nowhere");
    expect(await violations()).toEqual([]);
  });
});

describe("every page has one main landmark and one top-level heading", () => {
  it.each([
    ["/book/demo", ""],
    ["/booking", TOKEN],
    ["/sign-in", ""],
    ["/panel", ""],
    ["/panel/regulars", ""],
    ["/panel/students", ""],
    ["/panel/students/aaaaaaaa-0000-4000-8000-000000000001", ""],
    ["/panel/availability", ""],
    ["/statement", TOKEN],
    ["/nowhere", ""],
  ])("%s", async (path, hash) => {
    everything();
    if (path === "/sign-in") mockApi({ "GET /api/v1/me": () => json(401, {}) });
    open(path, hash);

    const [heading] = await screen.findAllByRole("heading", { level: 1 });

    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 1 })).toEqual([heading]);
    expect(document.title).not.toBe("");
  });
});

/** WCAG relative luminance of an sRGB colour written as #rrggbb. */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(a: string, b: string): number {
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (lighter! + 0.05) / (darker! + 0.05);
}

/** The colour tokens of one theme, read from the stylesheet itself. */
function tokens(css: string, theme: "light" | "dark"): Record<string, string> {
  const light = css.slice(css.indexOf(":root {"), css.indexOf("@media (prefers-color-scheme: dark)"));
  const dark = css.slice(css.indexOf("@media (prefers-color-scheme: dark)"), css.indexOf("*,"));
  const found: Record<string, string> = {};
  for (const [, name, value] of (theme === "light" ? light : dark).matchAll(
    /--color-([a-z-]+):\s*(#[0-9a-f]{6})/g,
  )) {
    found[name!] = value!;
  }
  return found;
}

describe.each(["light", "dark"] as const)("colour contrast in the %s theme", (theme) => {
  const color = tokens(readFileSync("src/styles.css", "utf8"), theme);

  // Text: WCAG 2.2 AA asks for 4.5:1.
  it.each([
    ["text", "bg"],
    ["text", "surface"],
    ["text", "accent-soft"],
    ["text-muted", "bg"],
    ["text-muted", "surface"],
    ["accent", "bg"],
    ["accent", "surface"],
    ["accent", "accent-soft"],
    ["accent-contrast", "accent"],
    ["danger", "bg"],
    ["danger", "surface"],
    ["warning", "surface"],
  ])("%s on %s is readable", (foreground, background) => {
    expect(contrast(color[foreground]!, color[background]!)).toBeGreaterThanOrEqual(4.5);
  });

  // Things that are not text but must be seen: 3:1. The focus ring is drawn
  // two pixels outside the control, so what it has to stand out from is the
  // page around the control, not the control's own fill.
  it.each([
    ["focus", "bg"],
    ["focus", "surface"],
    ["focus", "accent-soft"],
    ["text-muted", "surface"], // the border of a text field
    ["accent", "surface"], // the border of a secondary button and of today
  ])("%s against %s can be made out", (mark, background) => {
    expect(contrast(color[mark]!, color[background]!)).toBeGreaterThanOrEqual(3);
  });
});
