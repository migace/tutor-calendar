import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Slot } from "../../api/client";
import { SlotPicker } from "./SlotPicker";

const slots: Slot[] = [
  { start: "2026-11-17T14:00:00Z", end: "2026-11-17T15:00:00Z" },
  { start: "2026-11-17T15:00:00Z", end: "2026-11-17T16:00:00Z" },
  { start: "2026-11-21T08:00:00Z", end: "2026-11-21T09:00:00Z" },
];

function renderPicker(props: Partial<Parameters<typeof SlotPicker>[0]> = {}) {
  const onSelect = vi.fn();
  render(
    <SlotPicker
      slots={slots}
      timeZone="Europe/Warsaw"
      locale="en-GB"
      selected={null}
      onSelect={onSelect}
      {...props}
    />,
  );
  return { onSelect };
}

describe("SlotPicker", () => {
  it("shows one section per day with times in the display time zone", () => {
    renderPicker();

    const tuesday = screen.getByRole("region", { name: "Tuesday 17 November" });
    const saturday = screen.getByRole("region", { name: "Saturday 21 November" });

    expect(within(tuesday).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "15:00",
      "16:00",
    ]);
    expect(within(saturday).getAllByRole("button").map((b) => b.textContent)).toEqual(["09:00"]);
  });

  it("shows the same instants at different wall-clock times in another zone", () => {
    renderPicker({ timeZone: "America/New_York" });

    const tuesday = screen.getByRole("region", { name: "Tuesday 17 November" });

    expect(within(tuesday).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "09:00",
      "10:00",
    ]);
  });

  it("reports the slot the visitor picked", async () => {
    const { onSelect } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: "Tuesday 17 November, 16:00" }));

    expect(onSelect).toHaveBeenCalledExactlyOnceWith(slots[1]);
  });

  it("marks only the selected slot as pressed", () => {
    renderPicker({ selected: slots[1]! });

    expect(screen.getByRole("button", { name: "Tuesday 17 November, 16:00" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Tuesday 17 November, 15:00" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
