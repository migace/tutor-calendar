import { Link } from "react-router";

import type { Statement } from "../../api/client";
import { formatDay, formatMinutes } from "../../dates";
import { UI_LOCALE } from "../../i18n";

function describeBalance(minutes: number): string {
  if (minutes < 0) return `${formatMinutes(-minutes)} to pay for`;
  return `${formatMinutes(minutes)} left`;
}

interface StatementTableProps {
  statement: Statement;
  /** Builds the address of another month from its first day ("YYYY-MM-DD"). */
  monthLink: (month: string) => string;
}

/** One month of an account: where it started, what happened, where it ended. */
export function StatementTable({ statement, monthLink }: StatementTableProps) {
  const day = new Intl.DateTimeFormat(UI_LOCALE, {
    timeZone: statement.timezone,
    day: "numeric",
    month: "short",
  });
  const month = formatDay(statement.month, { month: "long", year: "numeric" });

  return (
    <section className="statement" aria-labelledby="statement-heading">
      <div className="week-bar">
        <div>
          <h2 className="step__heading" id="statement-heading">
            {month}
          </h2>
          <p className="statement__balance" role="status">
            Now: <strong>{describeBalance(statement.balance_minutes)}</strong>
          </p>
        </div>
        <nav className="week-bar__nav" aria-label="Months">
          <Link className="button button--secondary" to={monthLink(statement.previous)}>
            Previous
          </Link>
          <Link className="button button--secondary" to={monthLink(statement.next)}>
            Next
          </Link>
        </nav>
      </div>

      <table className="statement__table">
        <caption className="visually-hidden">
          Lesson time in {month}, with the balance before and after
        </caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">What</th>
            <th scope="col" className="statement__amount">
              Time
            </th>
          </tr>
        </thead>
        <tbody>
          <tr className="statement__total">
            <th scope="row" colSpan={2}>
              Balance at the start of the month
            </th>
            <td className="statement__amount">{formatMinutes(statement.opening_minutes)}</td>
          </tr>
          {statement.entries.length === 0 && (
            <tr>
              <td colSpan={3} className="week__empty">
                Nothing happened this month.
              </td>
            </tr>
          )}
          {statement.entries.map((entry) => (
            <tr key={entry.id}>
              <td>{day.format(new Date(entry.at))}</td>
              <td>{entry.note || (entry.kind === "purchase" ? "Lesson time bought" : entry.kind)}</td>
              <td className="statement__amount">
                {entry.minutes > 0 ? "+" : ""}
                {formatMinutes(entry.minutes)}
              </td>
            </tr>
          ))}
          <tr className="statement__total">
            <th scope="row" colSpan={2}>
              Balance at the end of the month
            </th>
            <td className="statement__amount">{formatMinutes(statement.closing_minutes)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}
