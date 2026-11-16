import { describe, expect, it } from "vitest";

import type { WeeklyRule } from "../../api/client";
import {
  problemsIn,
  suggestBlock,
  toDraft,
  toRules,
  withBlockAdded,
  withBlockChanged,
  withBlockRemoved,
  type Block,
  type Draft,
} from "./weeklyHours";

const block = (id: number, start: string, end: string): Block => ({ id, start, end });
/** A draft with the given blocks on Monday and nothing on other days. */
const monday = (...blocks: Block[]): Draft => [blocks, [], [], [], [], [], []];

describe("toDraft and toRules", () => {
  const rules: WeeklyRule[] = [
    { weekday: 0, start: "15:00:00", end: "19:00:00" },
    { weekday: 5, start: "09:00:00", end: "13:00:00" },
    { weekday: 0, start: "08:00:00", end: "10:00:00" },
  ];

  it("groups rules by weekday, earliest first, in the form a time input uses", () => {
    const draft = toDraft(rules);

    expect(draft).toHaveLength(7);
    expect(draft[0]!.map(({ start, end }) => [start, end])).toEqual([
      ["08:00", "10:00"],
      ["15:00", "19:00"],
    ]);
    expect(draft[5]!.map(({ start, end }) => [start, end])).toEqual([["09:00", "13:00"]]);
    expect(draft[1]).toEqual([]);
  });

  it("gives every block its own id", () => {
    const ids = toDraft(rules)
      .flat()
      .map((each) => each.id);

    expect(new Set(ids).size).toBe(3);
  });

  it("turns a draft back into rules without the editing-only fields", () => {
    expect(toRules(toDraft(rules))).toEqual([
      { weekday: 0, start: "08:00", end: "10:00" },
      { weekday: 0, start: "15:00", end: "19:00" },
      { weekday: 5, start: "09:00", end: "13:00" },
    ]);
  });
});

describe("editing a draft", () => {
  it("adds, changes and removes a block on one day without touching the others", () => {
    const start = toDraft([{ weekday: 2, start: "10:00:00", end: "11:00:00" }]);

    const added = withBlockAdded(start, 0);
    const id = added[0]![0]!.id;
    const changed = withBlockChanged(added, 0, id, { end: "13:30" });
    const removed = withBlockRemoved(changed, 0, id);

    expect(added[0]).toHaveLength(1);
    expect(changed[0]![0]).toMatchObject({ start: "09:00", end: "13:30" });
    expect(removed[0]).toEqual([]);
    for (const draft of [added, changed, removed]) expect(draft[2]).toBe(start[2]);
  });
});

describe("suggestBlock", () => {
  it("suggests a morning for an empty day", () => {
    expect(suggestBlock([])).toMatchObject({ start: "09:00", end: "12:00" });
  });

  it("suggests hours after the last block, leaving a break", () => {
    const suggestion = suggestBlock([block(1, "15:00", "17:30"), block(2, "08:00", "10:00")]);

    expect(suggestion).toMatchObject({ start: "18:30", end: "20:30" });
  });

  it("falls back to a morning when the day already runs late", () => {
    // Hours after 22:30 would run past midnight, which a single day cannot hold.
    expect(suggestBlock([block(1, "18:00", "22:30")])).toMatchObject({
      start: "09:00",
      end: "12:00",
    });
  });
});

describe("problemsIn", () => {
  it("finds nothing wrong with separate or touching blocks", () => {
    const draft = monday(block(1, "12:00", "15:00"), block(2, "09:00", "12:00"));

    expect(problemsIn(draft).size).toBe(0);
  });

  it("flags a block that ends before it starts, or is empty", () => {
    const problems = problemsIn(
      monday(block(1, "12:00", "09:00"), block(2, "10:00", "10:00"), block(3, "", "11:00")),
    );

    expect(problems.get(1)).toBe("order");
    expect(problems.get(2)).toBe("order");
    expect(problems.get(3)).toBe("missing");
  });

  it("flags the later of two overlapping blocks, whatever order they were typed in", () => {
    const problems = problemsIn(monday(block(1, "11:00", "13:00"), block(2, "09:00", "12:00")));

    expect([...problems.entries()]).toEqual([[1, "overlap"]]);
  });

  it("does not compare blocks on different days", () => {
    const draft: Draft = [[block(1, "09:00", "12:00")], [block(2, "09:00", "12:00")], [], [], [], [], []];

    expect(problemsIn(draft).size).toBe(0);
  });
});
