import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { fetchAccounts } from "../../api/client";
import { formatMinutes } from "../../dates";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";

export const ACCOUNTS_KEY = ["accounts"] as const;

export const studentPath = (email: string) => `/panel/students/${encodeURIComponent(email)}`;

/** Everyone the tutor teaches, with the lesson time each has paid for and not used. */
export function StudentsPage() {
  const all = useT();
  const t = all.students;
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: ({ signal }) => fetchAccounts(signal),
  });

  if (isPending) return <PageSkeleton label={t.loading} />;
  if (error) {
    return (
      <Notice tone="problem" title={t.loadFailedTitle}>
        <Button busy={isFetching} onClick={() => refetch()}>
          {all.common.tryAgain}
        </Button>
      </Notice>
    );
  }

  return (
    <section className="regulars" aria-labelledby="students-heading">
      <title>{t.pageTitle}</title>
      <header>
        <h1 className="week-bar__title" id="students-heading">
          {t.heading}
        </h1>
        <p className="page__meta">{t.intro}</p>
      </header>

      <OpenAccount />

      {data.length === 0 ? (
        <p className="week__empty">{t.empty}</p>
      ) : (
        <ul className="regulars__list">
          {data.map((account) => {
            const owes = account.balance_minutes < 0;
            return (
              <li key={account.email} className="day account">
                <div>
                  <Link className="link account__name" to={studentPath(account.email)}>
                    {account.name ?? account.email}
                  </Link>
                  {account.name && <p className="page__meta">{account.email}</p>}
                </div>
                <p className={`account__balance${owes ? " account__balance--owed" : ""}`}>
                  {owes
                    ? t.toPayFor(formatMinutes(-account.balance_minutes))
                    : t.left(formatMinutes(account.balance_minutes))}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

/** A way to an account by address, for a student who has not booked anything yet. */
function OpenAccount() {
  const t = useT().students;
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState<string>();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim().toLowerCase();
    if (!LOOKS_LIKE_EMAIL.test(address)) {
      setProblem(t.emailInvalid);
      input.current?.focus();
      return;
    }
    void navigate(studentPath(address));
  }

  return (
    <form className="form" noValidate onSubmit={handleSubmit}>
      <TextField
        ref={input}
        label={t.find}
        hint={t.findHint}
        type="email"
        name="email"
        autoComplete="off"
        inputMode="email"
        value={email}
        error={problem}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Button type="submit" variant="secondary">
        {t.open}
      </Button>
    </form>
  );
}
