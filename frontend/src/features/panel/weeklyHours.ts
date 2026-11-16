import type { WeeklyRule } from "../../api/client";

/** Monday to Sunday, as the API numbers them. */
export const WEEKDAY_COUNT = 7;

/** One block of hours while it is being edited. Times are "HH:MM", or "" while empty. */
export interface Block {
  /** Stable identity for React and for labels; never sent to the server. */
  id: number;
  start: string;
  end: string;
}

/** The blocks of each weekday, Monday first. */
export type Draft = readonly (readonly Block[])[];

/** What is wrong with a block. The interface turns each into a sentence. */
export type BlockProblem = "missing" | "order" | "overlap";

let nextId = 1;
const newId = () => nextId++;

/** "15:00:00" from the API becomes "15:00", the form `<input type="time">` uses. */
const toMinutes = (time: string) => time.slice(0, 5);

export function toDraft(rules: readonly WeeklyRule[]): Draft {
  return Array.from({ length: WEEKDAY_COUNT }, (_, weekday) =>
    rules
      .filter((rule) => rule.weekday === weekday)
      .map((rule) => ({ id: newId(), start: toMinutes(rule.start), end: toMinutes(rule.end) }))
      .sort((a, b) => a.start.localeCompare(b.start)),
  );
}

export function toRules(draft: Draft): WeeklyRule[] {
  return draft.flatMap((blocks, weekday) =>
    blocks.map(({ start, end }) => ({ weekday, start, end })),
  );
}

function addHours(time: string, hours: number): string {
  const hour = Math.min(23, Number(time.slice(0, 2)) + hours);
  return `${String(hour).padStart(2, "0")}:${time.slice(3, 5)}`;
}

/** A new block for a day: after the last one if there is room, otherwise a morning. */
export function suggestBlock(blocks: readonly Block[]): Block {
  const latestEnd = blocks
    .map((block) => block.end)
    .sort()
    .at(-1);
  if (latestEnd && latestEnd <= "20:00") {
    const start = addHours(latestEnd, 1);
    return { id: newId(), start, end: addHours(start, 2) };
  }
  return { id: newId(), start: "09:00", end: "12:00" };
}

export function withBlockAdded(draft: Draft, weekday: number): Draft {
  return draft.map((blocks, day) =>
    day === weekday ? [...blocks, suggestBlock(blocks)] : blocks,
  );
}

export function withBlockRemoved(draft: Draft, weekday: number, id: number): Draft {
  return draft.map((blocks, day) =>
    day === weekday ? blocks.filter((block) => block.id !== id) : blocks,
  );
}

export function withBlockChanged(
  draft: Draft,
  weekday: number,
  id: number,
  change: Partial<Pick<Block, "start" | "end">>,
): Draft {
  return draft.map((blocks, day) =>
    day === weekday
      ? blocks.map((block) => (block.id === id ? { ...block, ...change } : block))
      : blocks,
  );
}

/**
 * What is wrong with each block, by block id. Mirrors the rules the server
 * enforces, so that most mistakes are caught before a round trip; the server
 * still has the final say.
 *
 * "HH:MM" strings compare correctly as text, which keeps this free of dates.
 */
export function problemsIn(draft: Draft): Map<number, BlockProblem> {
  const problems = new Map<number, BlockProblem>();
  for (const blocks of draft) {
    for (const block of blocks) {
      if (!block.start || !block.end) {
        problems.set(block.id, "missing");
      } else if (block.start >= block.end) {
        problems.set(block.id, "order");
      }
    }
    const valid = blocks
      .filter((block) => !problems.has(block.id))
      .sort((a, b) => a.start.localeCompare(b.start));
    for (let index = 1; index < valid.length; index++) {
      // Blocks that merely touch (12:00 after 12:00) are fine.
      if (valid[index]!.start < valid[index - 1]!.end) {
        problems.set(valid[index]!.id, "overlap");
      }
    }
  }
  return problems;
}
