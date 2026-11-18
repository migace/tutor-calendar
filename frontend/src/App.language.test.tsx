import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Profile, Statement, Week } from "./api/client";
import { App } from "./App";
import { setLanguage } from "./i18n";
import { en } from "./i18n/en";
import { pl } from "./i18n/pl";
import { json, mockApi } from "./test/mockApi";

const PROFILE: Profile = {
  slug: "demo",
  display_name: "Demo Tutor",
  email: "demo@example.com",
  timezone: "Europe/Warsaw",
  lesson_minutes: 60,
};

const WEEK: Week = {
  timezone: "Europe/Warsaw",
  today: "2026-11-16",
  previous: "2026-11-09",
  next: "2026-11-23",
  days: Array.from({ length: 7 }, (_, n) => ({
    date: `2026-11-${16 + n}`,
    lessons:
      n === 1
        ? [
            {
              id: "0b5c1f4e-0000-4000-8000-000000000001",
              start: "2026-11-17T14:00:00Z",
              end: "2026-11-17T15:00:00Z",
              student_name: "Anna Nowak",
              student_email: "anna@example.com",
              status: "cancelled",
              cancelled_by: "student",
              cancelled_late: true,
              series_id: null,
            },
          ]
        : [],
  })),
};

const STATEMENT: Statement = {
  tutor_name: "Demo Tutor",
  timezone: "Europe/Warsaw",
  student_email: "anna@example.com",
  student_name: "Anna Nowak",
  month: "2026-11-01",
  previous: "2026-10-01",
  next: "2026-12-01",
  nothing_recorded: false,
  opening_minutes: 600,
  closing_minutes: 480,
  balance_minutes: 480,
  share_token: null,
  entries: [
    {
      id: "11111111-0000-4000-8000-000000000001",
      kind: "lesson",
      minutes: -60,
      note: "Lesson",
      at: "2026-11-10T16:00:00Z",
      lesson_id: "22222222-0000-4000-8000-000000000001",
    },
    {
      id: "11111111-0000-4000-8000-000000000002",
      kind: "lesson",
      minutes: -60,
      note: "Lesson cancelled late",
      at: "2026-11-17T16:00:00Z",
      lesson_id: "22222222-0000-4000-8000-000000000002",
    },
  ],
};

function renderApp(path: string, hash = "") {
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

afterEach(() => {
  setLanguage("en");
  window.localStorage.clear();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

/** Every leaf of a catalog, as "section.key" with a sample of what it says. */
function leaves(catalog: object, prefix = ""): Map<string, string> {
  const found = new Map<string, string>();
  for (const [key, value] of Object.entries(catalog)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") found.set(path, value);
    else if (typeof value === "function") found.set(path, String(value(2, "x", "y")));
    else for (const [inner, text] of leaves(value, path)) found.set(inner, text);
  }
  return found;
}

describe("the Polish catalog", () => {
  it("says everything the English one says", () => {
    expect([...leaves(pl).keys()]).toEqual([...leaves(en).keys()]);
  });

  it("is actually translated", () => {
    const english = leaves(en);
    const same = [...leaves(pl)]
      .filter(([key, text]) => english.get(key) === text)
      .map(([key]) => key);

    // Names are the same in both languages; sentences are not. The third is a
    // page title made of nothing but the student's name and the site's.
    expect(same).toEqual(["common.siteName", "panel.nav", "student.pageTitle"]);
  });

  it("uses the right plural form for each number", () => {
    expect([0, 1, 2, 4, 5, 12, 22, 25].map((count) => pl.week.lessons(count))).toEqual([
      "Brak lekcji",
      "1 lekcja",
      "2 lekcje",
      "4 lekcje",
      "5 lekcji",
      "12 lekcji",
      "22 lekcje",
      "25 lekcji",
    ]);
    expect(pl.series.left(1, "24 listopada")).toBe(
      "Została jeszcze 1 lekcja, najbliższa: 24 listopada.",
    );
    expect(pl.series.left(3, "24 listopada")).toBe(
      "Zostały jeszcze 3 lekcje, najbliższa: 24 listopada.",
    );
    expect(pl.series.left(5, "24 listopada")).toBe(
      "Zostało jeszcze 5 lekcji, najbliższa: 24 listopada.",
    );
  });
});

describe("switching language", () => {
  const signedIn = () => json(200, PROFILE);

  it("turns the whole page, dates included, into Polish and back", async () => {
    mockApi({ "GET /api/v1/me": signedIn, "GET /api/v1/me/week": () => json(200, WEEK) });
    const user = renderApp("/panel");

    expect(await screen.findByRole("heading", { name: "16 – 22 November 2026" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en");

    await user.click(screen.getByRole("button", { name: "Polski" }));

    expect(screen.getByRole("heading", { name: "16 – 22 listopada 2026" })).toBeVisible();
    const tuesday = screen.getByRole("listitem", { name: /wtorek 17 lis/ });
    expect(within(tuesday).getByText("Odwołana przez ucznia po terminie")).toBeVisible();
    expect(screen.getByRole("link", { name: "Tydzień" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("status")).toHaveTextContent("Brak lekcji · Godziny w strefie");
    // Screen readers take their pronunciation from this.
    expect(document.documentElement.lang).toBe("pl");
    expect(document.title).toBe("Twój tydzień · Tutor Calendar");

    await user.click(screen.getByRole("button", { name: "English" }));

    expect(screen.getByRole("link", { name: "Week" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en");
  });

  it("marks the language in use, and each name in its own language", async () => {
    mockApi({ "GET /api/v1/me": () => json(401, {}) });
    const user = renderApp("/sign-in");

    const group = await screen.findByRole("group", { name: "Language" });
    const polish = within(group).getByRole("button", { name: "Polski" });
    expect(polish).toHaveAttribute("lang", "pl");
    expect(polish).toHaveAttribute("aria-pressed", "false");

    await user.click(polish);

    expect(polish).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("group", { name: "Język" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Logowanie" })).toBeVisible();
  });

  it("remembers the choice for the next visit", async () => {
    mockApi({ "GET /api/v1/me": () => json(401, {}) });
    const user = renderApp("/sign-in");

    await user.click(await screen.findByRole("button", { name: "Polski" }));

    expect(window.localStorage.getItem("tutor-calendar-language")).toBe("pl");
  });

  it("translates what the system wrote on a statement, and leaves the tutor's words alone", async () => {
    const withNote = {
      ...STATEMENT,
      entries: [
        ...STATEMENT.entries,
        {
          id: "11111111-0000-4000-8000-000000000003",
          kind: "purchase",
          minutes: 600,
          note: "Pakiet świąteczny",
          at: "2026-11-20T09:00:00Z",
          lesson_id: null,
        },
      ],
    };
    mockApi({ "GET /api/v1/statement": () => json(200, withNote) });
    setLanguage("pl");

    renderApp("/statement", "#token=c2hhcmU.signature");

    const table = await screen.findByRole("table", { name: /Czas lekcji: listopad 2026/ });
    const rows = within(table)
      .getAllByRole("row")
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "DataCoCzas",
      "Saldo na początku miesiąca10 h",
      "10 lisLekcja−1 h",
      "17 lisLekcja odwołana po terminie−1 h",
      "20 lisPakiet świąteczny+10 h",
      "Saldo na koniec miesiąca8 h",
    ]);
    expect(screen.getByText("zostało 8 h")).toBeVisible();
  });
});

describe("a public demonstration", () => {
  it("says what it is and lets anyone into the demo tutor's panel", async () => {
    let signedIn = false;
    const api = mockApi({
      "GET /api/v1/config": () => json(200, { demo_mode: true }),
      "GET /api/v1/me": () => (signedIn ? json(200, PROFILE) : json(401, {})),
      "POST /api/v1/auth/demo-session": () => {
        signedIn = true;
        return json(200, PROFILE);
      },
      "GET /api/v1/me/week": () => json(200, WEEK),
    });
    const user = renderApp("/sign-in");

    expect(await screen.findByText(/This is a demonstration with made-up students/)).toBeVisible();
    await user.click(await screen.findByRole("button", { name: "Enter the demo tutor’s panel" }));

    expect(await screen.findByRole("heading", { name: "16 – 22 November 2026" })).toBeVisible();
    expect(api.callsTo("POST /api/v1/auth/demo-session")).toHaveLength(1);
    // From inside the panel the banner points back at the public side.
    expect(screen.getByRole("link", { name: "See the booking page" })).toHaveAttribute(
      "href",
      "/book/demo",
    );
  });

  it("shows neither the banner nor the shortcut anywhere else", async () => {
    mockApi({ "GET /api/v1/me": () => json(401, {}) });

    renderApp("/sign-in");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.queryByText(/demonstration/)).toBeNull();
    expect(screen.queryByRole("button", { name: /demo/i })).toBeNull();
  });
});

describe("the skip link", () => {
  it("moves focus to the page content without touching the address", async () => {
    mockApi({ "GET /api/v1/statement": () => json(200, STATEMENT) });
    const user = renderApp("/statement", "#token=c2hhcmU.signature");
    await screen.findByRole("table");

    await user.click(screen.getByRole("link", { name: "Skip to content" }));

    expect(screen.getByRole("main")).toHaveFocus();
    // The token in the fragment is what makes this page work: it must survive.
    expect(window.location.hash).toBe("#token=c2hhcmU.signature");
  });
});
