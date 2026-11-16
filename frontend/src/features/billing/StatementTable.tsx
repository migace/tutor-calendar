import { Link } from "react-router";

import type { LedgerEntry, Statement } from "../../api/client";
import { currentLocale, useT, type Messages } from "../../i18n";
import { formatDay, formatMinutes } from "../../dates";

/** What an entry is, in the reader's language. */
function describeEntry(entry: LedgerEntry, t: Messages["statement"]): string {
  // Charges are written by the system with a fixed note, which can be translated.
  if (entry.kind === "lesson") return t.lessonNotes[entry.note] ?? entry.note;
  // Anything else carries the tutor's own words, shown as written.
  if (entry.note) return entry.note;
  return entry.kind === "purchase" ? t.purchase : t.adjustment;
}

interface StatementTableProps {
  statement: Statement;
  /** Builds the address of another month from its first day ("YYYY-MM-DD"). */
  monthLink: (month: string) => string;
}

/** One month of an account: where it started, what happened, where it ended. */
export function StatementTable({ statement, monthLink }: StatementTableProps) {
  const t = useT().statement;
  const day = new Intl.DateTimeFormat(currentLocale(), {
    timeZone: statement.timezone,
    day: "numeric",
    month: "short",
  });
  const month = formatDay(statement.month, { month: "long", year: "numeric" });
  const now =
    statement.balance_minutes < 0
      ? t.toPayFor(formatMinutes(-statement.balance_minutes))
      : t.left(formatMinutes(statement.balance_minutes));

  return (
    <section className="statement" aria-labelledby="statement-heading">
      <div className="week-bar">
        <div>
          <h2 className="step__heading" id="statement-heading">
            {month}
          </h2>
          <p className="statement__balance" role="status">
            {t.now} <strong>{now}</strong>
          </p>
        </div>
        <nav className="week-bar__nav" aria-label={t.monthsNav}>
          <Link className="button button--secondary" to={monthLink(statement.previous)}>
            {t.previous}
          </Link>
          <Link className="button button--secondary" to={monthLink(statement.next)}>
            {t.next}
          </Link>
        </nav>
      </div>

      <table className="statement__table">
        <caption className="visually-hidden">{t.caption(month)}</caption>
        <thead>
          <tr>
            <th scope="col">{t.date}</th>
            <th scope="col">{t.what}</th>
            <th scope="col" className="statement__amount">
              {t.time}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr className="statement__total">
            <th scope="row" colSpan={2}>
              {t.opening}
            </th>
            <td className="statement__amount">{formatMinutes(statement.opening_minutes)}</td>
          </tr>
          {statement.entries.length === 0 && (
            <tr>
              <td colSpan={3} className="week__empty">
                {t.nothing}
              </td>
            </tr>
          )}
          {statement.entries.map((entry) => (
            <tr key={entry.id}>
              <td>{day.format(new Date(entry.at))}</td>
              <td>{describeEntry(entry, t)}</td>
              <td className="statement__amount">
                {entry.minutes > 0 ? "+" : ""}
                {formatMinutes(entry.minutes)}
              </td>
            </tr>
          ))}
          <tr className="statement__total">
            <th scope="row" colSpan={2}>
              {t.closing}
            </th>
            <td className="statement__amount">{formatMinutes(statement.closing_minutes)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}
