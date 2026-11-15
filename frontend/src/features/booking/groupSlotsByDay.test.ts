import { describe, expect, it } from "vitest";

import type { Slot } from "../../api/client";
import { groupSlotsByDay } from "./groupSlotsByDay";

function slot(start: string): Slot {
  const end = new Date(new Date(start).getTime() + 60 * 60 * 1000).toISOString();
  return { start, end };
}

describe("groupSlotsByDay", () => {
  it("returns nothing for no slots", () => {
    expect(groupSlotsByDay([], "Europe/Warsaw")).toEqual([]);
  });

  it("keeps slots in order and groups consecutive ones on the same day", () => {
    const slots = [
      slot("2026-11-17T14:00:00Z"),
      slot("2026-11-17T15:00:00Z"),
      slot("2026-11-18T14:00:00Z"),
    ];

    const groups = groupSlotsByDay(slots, "Europe/Warsaw");

    expect(groups.map((group) => [group.day, group.slots.length])).toEqual([
      ["2026-11-17", 2],
      ["2026-11-18", 1],
    ]);
  });

  it("decides the day in the display time zone, not in UTC", () => {
    const lateEvening = [slot("2026-11-17T23:30:00Z")];

    expect(groupSlotsByDay(lateEvening, "UTC")[0]?.day).toBe("2026-11-17");
    expect(groupSlotsByDay(lateEvening, "Europe/Warsaw")[0]?.day).toBe("2026-11-18");
    expect(groupSlotsByDay(lateEvening, "America/Los_Angeles")[0]?.day).toBe("2026-11-17");
  });
});
