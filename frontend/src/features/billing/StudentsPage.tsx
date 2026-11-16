import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { fetchAccounts } from "../../api/client";
import { formatMinutes } from "../../dates";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";

export const ACCOUNTS_KEY = ["accounts"] as const;

export const studentPath = (email: string) => `/panel/students/${encodeURIComponent(email)}`;

/** Everyone the tutor teaches, with the lesson time each has paid for and not used. */
export function StudentsPage() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: ({ signal }) => fetchAccounts(signal),
  });

  if (isPending) return <PageSkeleton label="Loading your students…" />;
  if (error) {
    return (
      <Notice tone="problem" title="We could not load your students">
        <Button busy={isFetching} onClick={() => refetch()}>
          Try again
        </Button>
      </Notice>
    );
  }

  return (
    <section className="regulars" aria-labelledby="students-heading">
      <title>Students · Tutor Calendar</title>
      <header>
        <h1 className="week-bar__title" id="students-heading">
          Students
        </h1>
        <p className="page__meta">
          Lesson time each student has paid for and not used yet. A lesson is taken off once it
          is over.
        </p>
      </header>

      <OpenAccount />

      {data.length === 0 ? (
        <p className="week__empty">Students also appear here once they book a lesson.</p>
      ) : (
        <ul className="regulars__list">
          {data.map((account) => (
            <li key={account.email} className="day account">
              <div>
                <Link className="link account__name" to={studentPath(account.email)}>
                  {account.name ?? account.email}
                </Link>
                {account.name && <p className="page__meta">{account.email}</p>}
              </div>
              <p className={`account__balance${account.balance_minutes < 0 ? " account__balance--owed" : ""}`}>
                {account.balance_minutes < 0
                  ? `${formatMinutes(-account.balance_minutes)} to pay for`
                  : `${formatMinutes(account.balance_minutes)} left`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

/** A way to an account by address, for a student who has not booked anything yet. */
function OpenAccount() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState<string>();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim().toLowerCase();
    if (!LOOKS_LIKE_EMAIL.test(address)) {
      setProblem("Enter an email address like name@example.com.");
      input.current?.focus();
      return;
    }
    void navigate(studentPath(address));
  }

  return (
    <form className="form" noValidate onSubmit={handleSubmit}>
      <TextField
        ref={input}
        label="Find or add a student by email"
        hint="To record a package for someone who has not booked a lesson yet."
        type="email"
        name="email"
        autoComplete="off"
        inputMode="email"
        value={email}
        error={problem}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Button type="submit" variant="secondary">
        Open account
      </Button>
    </form>
  );
}
