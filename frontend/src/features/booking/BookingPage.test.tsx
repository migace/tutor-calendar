import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Slot, SlotsResponse } from "../../api/client";
import { BookingPage } from "./BookingPage";

const TUESDAY_3PM: Slot = { start: "2026-11-17T14:00:00Z", end: "2026-11-17T15:00:00Z" };
const TUESDAY_4PM: Slot = { start: "2026-11-17T15:00:00Z", end: "2026-11-17T16:00:00Z" };

function slotsResponse(slots: Slot[]): SlotsResponse {
  return {
    tutor: {
      slug: "demo",
      display_name: "Demo Tutor",
      timezone: "Europe/Warsaw",
      lesson_minutes: 60,
    },
    slots,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const booked = () => json(201, { id: "0b5c1f4e-0000-4000-8000-000000000001", ...TUESDAY_3PM });
const networkDown = () => Promise.reject(new TypeError("Failed to fetch"));

type Reply = () => Response | Promise<Response>;

/**
 * A stand-in for the API. `slotLists` are served in order, the last one for
 * ever; `bookingReplies` are served in order, one per POST.
 */
function mockApi(slotLists: Slot[][], bookingReplies: Reply[] = []) {
  const lists = [...slotLists];
  const replies = [...bookingReplies];
  const posts: { key: string | null; body: unknown }[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({
        key: new Headers(init.headers).get("Idempotency-Key"),
        body: JSON.parse(String(init.body)),
      });
      const reply = replies.shift();
      if (!reply) throw new Error(`unexpected POST to ${String(input)}`);
      return reply();
    }
    const list = lists.length > 1 ? lists.shift()! : lists[0]!;
    return json(200, slotsResponse(list));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { posts };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retryDelay: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <BookingPage slug="demo" timeZone="Europe/Warsaw" />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

async function pickTime(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(await screen.findByRole("button", { name: label }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

async function fillIn(user: ReturnType<typeof userEvent.setup>, name: string, email: string) {
  await user.type(screen.getByLabelText("Student's name"), name);
  await user.type(screen.getByLabelText("Email address"), email);
  await user.click(screen.getByRole("button", { name: "Book lesson" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("BookingPage", () => {
  it("books the chosen time and confirms it", async () => {
    const { posts } = mockApi([[TUESDAY_3PM, TUESDAY_4PM], [TUESDAY_4PM]], [booked]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    expect(screen.getByRole("heading", { name: "Your details" })).toHaveFocus();
    expect(screen.getByText("Tuesday 17 November, 15:00–16:00")).toBeInTheDocument();

    await fillIn(user, "  Anna Nowak ", "anna@example.com");

    const confirmation = await screen.findByRole("heading", { name: "You’re booked" });
    expect(confirmation).toHaveFocus();
    expect(screen.getByText("Tuesday 17 November, 15:00–16:00")).toBeInTheDocument();
    expect(posts).toEqual([
      {
        key: expect.stringMatching(/^[0-9a-f-]{36}$/),
        body: {
          start: TUESDAY_3PM.start,
          student_name: "Anna Nowak",
          student_email: "anna@example.com",
        },
      },
    ]);

    // Booking another lesson starts from a fresh list without the taken time.
    await user.click(screen.getByRole("button", { name: "Book another lesson" }));
    expect(await screen.findByRole("button", { name: "Tuesday 17 November, 16:00" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Tuesday 17 November, 15:00" })).toBeNull();
  });

  it("retries a failed request with the same idempotency key", async () => {
    const { posts } = mockApi([[TUESDAY_3PM]], [networkDown, () => json(503, {}), booked]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await fillIn(user, "Anna Nowak", "anna@example.com");

    expect(await screen.findByRole("heading", { name: "You’re booked" })).toBeInTheDocument();
    expect(posts).toHaveLength(3);
    expect(new Set(posts.map((post) => post.key)).size).toBe(1);
  });

  it("keeps the key when the visitor retries by hand, and changes it with the request", async () => {
    const down = [networkDown, networkDown, networkDown];
    const { posts } = mockApi([[TUESDAY_3PM]], [...down, ...down, booked]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await fillIn(user, "Anna Nowak", "anna@example.com");
    expect(await screen.findByRole("alert")).toHaveTextContent("it is safe to try again");

    // The very same request again: same key.
    await user.click(screen.getByRole("button", { name: "Book lesson" }));
    await waitFor(() => expect(posts).toHaveLength(6));
    expect(new Set(posts.map((post) => post.key)).size).toBe(1);

    // A different request (another email) must not reuse it.
    await user.clear(screen.getByLabelText("Email address"));
    await user.type(screen.getByLabelText("Email address"), "anna.nowak@example.com");
    await user.click(screen.getByRole("button", { name: "Book lesson" }));

    expect(await screen.findByRole("heading", { name: "You’re booked" })).toBeInTheDocument();
    expect(posts[6]!.key).not.toBe(posts[0]!.key);
  });

  it("sends the visitor back to pick another time when theirs was just taken", async () => {
    const taken = () => json(409, { detail: "this time has just been booked by someone else" });
    const { posts } = mockApi([[TUESDAY_3PM, TUESDAY_4PM], [TUESDAY_4PM]], [taken]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await fillIn(user, "Anna Nowak", "anna@example.com");

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent("That time is no longer available");
    expect(screen.getByRole("heading", { name: "That time is no longer available" })).toHaveFocus();
    // A refusal is final: asking again would not help, so there is no retry.
    expect(posts).toHaveLength(1);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Tuesday 17 November, 15:00" })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: "Tuesday 17 November, 16:00" })).toBeVisible();
    expect(screen.getByText("Pick a time to continue.")).toBeInTheDocument();
  });

  it("points out missing details without sending anything", async () => {
    const { posts } = mockApi([[TUESDAY_3PM]]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await user.type(screen.getByLabelText("Email address"), "anna@");
    await user.click(screen.getByRole("button", { name: "Book lesson" }));

    const name = screen.getByLabelText("Student's name");
    expect(name).toHaveFocus();
    expect(name).toHaveAccessibleDescription(/Enter the student's name\./);
    expect(screen.getByLabelText("Email address")).toHaveAccessibleDescription(
      /like name@example\.com/,
    );
    expect(posts).toHaveLength(0);
  });

  it("says so when the server rejects the details", async () => {
    mockApi([[TUESDAY_3PM]], [() => json(422, { detail: [] })]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await fillIn(user, "Anna Nowak", "anna@localhost.x");

    expect(await screen.findByRole("alert")).toHaveTextContent("Check the name and email");
    expect(screen.getByRole("heading", { name: "Your details" })).toBeInTheDocument();
  });

  it("lets the visitor go back and choose a different time", async () => {
    mockApi([[TUESDAY_3PM, TUESDAY_4PM]]);
    const user = renderPage();

    await pickTime(user, "Tuesday 17 November, 15:00");
    await user.click(screen.getByRole("button", { name: "Change time" }));

    expect(screen.getByRole("button", { name: "Tuesday 17 November, 15:00" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await pickTime(user, "Tuesday 17 November, 16:00");
    expect(screen.getByText("Tuesday 17 November, 16:00–17:00")).toBeInTheDocument();
  });
});
