import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, fetchAccounts, openAccount } from "../../api/client";
import { formatMinutes } from "../../dates";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";
import { initials } from "../panel/PanelLayout";

export const ACCOUNTS_KEY = ["accounts"] as const;

/** A student's page. Named by id: an address here would end up in server logs. */
export const studentPath = (studentId: string) =>
  `/panel/students/${encodeURIComponent(studentId)}`;

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
      <header className="page-head">
        <h1 className="week-bar__title" id="students-heading">
          {t.heading}
        </h1>
        <p className="page__meta">{t.intro}</p>
      </header>

      <OpenAccount />

      {data.length === 0 ? (
        <p className="week__empty">{t.empty}</p>
      ) : (
        <ul className="accounts">
          {data.map((account) => {
            const owes = account.balance_minutes < 0;
            return (
              <li key={account.id} className="account">
                <span className="avatar" aria-hidden="true">
                  {initials(account.name ?? account.email)}
                </span>
                <div className="account__who">
                  <Link className="link account__name" to={studentPath(account.id)}>
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
  // The address goes to the server in the body of a request, and the page that
  // opens is named by the id that comes back.
  const open = useMutation({
    mutationFn: openAccount,
    onSuccess: (account) => void navigate(studentPath(account.id)),
    onError: (error) => {
      // The server checks addresses more strictly than the pattern above.
      if (error instanceof ApiError && error.status === 422) {
        setProblem(t.emailInvalid);
        input.current?.focus();
      }
    },
  });
  const failed = open.isError && !(open.error instanceof ApiError && open.error.status === 422);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim().toLowerCase();
    if (!LOOKS_LIKE_EMAIL.test(address)) {
      setProblem(t.emailInvalid);
      input.current?.focus();
      return;
    }
    setProblem(undefined);
    open.mutate(address);
  }

  return (
    <form className="form form--inline" noValidate onSubmit={handleSubmit}>
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
        onChange={(event) => {
          setEmail(event.target.value);
          open.reset();
        }}
      />
      <Button type="submit" variant="secondary" busy={open.isPending}>
        {open.isPending ? t.opening : t.open}
      </Button>
      {failed && (
        <p className="form__error form__error--row" role="alert">
          {t.openFailed}
        </p>
      )}
    </form>
  );
}
