import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import {
  ApiError,
  fetchStatement,
  recordEntry,
  type NewEntry,
  type Statement,
} from "../../api/client";
import { formatMinutes } from "../../dates";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";
import { StatementTable } from "./StatementTable";
import { ACCOUNTS_KEY } from "./StudentsPage";

/** One student's account, as their tutor sees it: the statement, and a way to add to it. */
export function StudentPage() {
  const email = useParams().email!;
  const [params] = useSearchParams();
  const month = params.get("month");
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["statement", email, month],
    queryFn: ({ signal }) => fetchStatement(email, month, signal),
    placeholderData: keepPreviousData,
    retry: (failures, failure) => failures < 1 && !(failure instanceof ApiError),
  });

  if (isPending) return <PageSkeleton label="Loading the account…" />;
  if (error instanceof ApiError && error.status === 404) {
    // Not a dead end: a tutor often sells a package before the first lesson,
    // and recording it is what opens the account.
    return (
      <div className="regulars">
        <title>{`${email} · Tutor Calendar`}</title>
        <header>
          <p>
            <Link className="link" to="/panel/students">
              All students
            </Link>
          </p>
          <h1 className="week-bar__title">{email}</h1>
        </header>
        <Notice title="Nothing is recorded for this address yet">
          <p>
            Record lesson time below to open an account for this student. Check the address
            first: it is how their lessons will be matched to the account.
          </p>
        </Notice>
        <AddTime email={email} />
      </div>
    );
  }
  if (error) {
    return (
      <Notice tone="problem" title="We could not load the account">
        <Button busy={isFetching} onClick={() => refetch()}>
          Try again
        </Button>
      </Notice>
    );
  }

  return (
    <div className="regulars" aria-busy={isFetching}>
      <title>{`${data.student_name ?? data.student_email} · Tutor Calendar`}</title>
      <header>
        <p>
          <Link className="link" to="/panel/students">
            All students
          </Link>
        </p>
        <h1 className="week-bar__title">{data.student_name ?? data.student_email}</h1>
        {data.student_name && <p className="page__meta">{data.student_email}</p>}
      </header>

      <StatementTable statement={data} monthLink={(first) => `?month=${first}`} />
      <AddTime email={email} />
      <ParentLink statement={data} />
    </div>
  );
}

type Kind = NewEntry["kind"];

function AddTime({ email }: { email: string }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<Kind>("purchase");
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<{ hours?: string; note?: string }>({});
  const hoursInput = useRef<HTMLInputElement>(null);
  const noteInput = useRef<HTMLInputElement>(null);
  // One id per distinct entry, reused when the same entry is sent again, so a
  // repeat after a lost response cannot credit the package twice.
  const attempt = useRef<{ entry: string; id: string } | null>(null);

  const record = useMutation({
    mutationFn: (entry: NewEntry) => {
      const fingerprint = JSON.stringify(entry);
      if (attempt.current?.entry !== fingerprint) {
        attempt.current = { entry: fingerprint, id: crypto.randomUUID() };
      }
      return recordEntry(email, attempt.current.id, entry);
    },
    onSuccess: () => {
      // The next entry is a new one even if it looks the same: ten hours twice
      // is two packages.
      attempt.current = null;
      setHours("");
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["statement", email] });
      void queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY });
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const minutes = Math.round(Number(hours.replace(",", ".")) * 60);
    const found: typeof problems = {};
    if (!hours.trim() || !Number.isFinite(minutes) || minutes === 0) {
      found.hours = "Enter a number of hours, such as 10 or 1.5.";
    } else if (kind === "purchase" && minutes < 0) {
      found.hours = "A package adds time. To take time away, record a correction.";
    }
    if (kind === "adjustment" && !note.trim()) {
      found.note = "Say what is being corrected. The parent sees this on the statement.";
    }
    setProblems(found);
    if (found.hours) return hoursInput.current?.focus();
    if (found.note) return noteInput.current?.focus();
    record.mutate({ kind, minutes, note: note.trim() });
  }

  const edited = () => record.reset();

  return (
    <section aria-labelledby="add-time-heading">
      <h2 className="step__heading" id="add-time-heading">
        Add lesson time
      </h2>
      <form className="form" noValidate onSubmit={handleSubmit}>
        <fieldset className="choice">
          <legend className="field__label">What is it?</legend>
          {(
            [
              ["purchase", "A package the student paid for"],
              ["adjustment", "A correction"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="choice__option">
              <input
                type="radio"
                name="kind"
                value={value}
                checked={kind === value}
                onChange={() => {
                  setKind(value);
                  edited();
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <TextField
          ref={hoursInput}
          label="Hours"
          hint={
            kind === "purchase"
              ? "For example 10, or 7.5."
              : "Use a minus to take time away, for example -1."
          }
          name="hours"
          inputMode="decimal"
          autoComplete="off"
          required
          value={hours}
          error={problems.hours}
          onChange={(event) => {
            setHours(event.target.value);
            edited();
          }}
        />
        <TextField
          ref={noteInput}
          label={kind === "purchase" ? "Note (optional)" : "Reason"}
          hint="Shown on the statement."
          name="note"
          maxLength={200}
          autoComplete="off"
          value={note}
          error={problems.note}
          onChange={(event) => {
            setNote(event.target.value);
            edited();
          }}
        />
        <p className="page__meta">
          Entries cannot be edited or removed afterwards. A mistake is put right with a correction,
          so the statement always shows what really happened.
        </p>
        {record.isError && (
          <p className="form__error" role="alert">
            {record.error instanceof ApiError && record.error.status === 422
              ? `This could not be recorded${record.error.detail ? `: ${record.error.detail}` : ""}.`
              : "We could not record this. Nothing was added; it is safe to try again."}
          </p>
        )}
        <p className="hours__status" role="status">
          {record.isSuccess &&
            `Recorded ${record.data.minutes > 0 ? "+" : ""}${formatMinutes(record.data.minutes)}.`}
        </p>
        <Button type="submit" busy={record.isPending}>
          {record.isPending ? "Recording…" : "Record"}
        </Button>
      </form>
    </section>
  );
}

function ParentLink({ statement }: { statement: Statement }) {
  const [copied, setCopied] = useState(false);
  if (!statement.share_token) return null;
  // In the fragment, which browsers do not send to servers.
  const path = `/statement#token=${statement.share_token}`;
  const address = `${window.location.origin}${path}`;

  return (
    <section aria-labelledby="parent-link-heading">
      <h2 className="step__heading" id="parent-link-heading">
        Link for the parent
      </h2>
      <p className="page__meta">
        Anyone with this link can read this student&rsquo;s statements, and nothing else. It
        cannot be used to change anything.
      </p>
      <p className="share">
        <Link className="link" to={path}>
          Open the parent&rsquo;s view
        </Link>
        <Button
          variant="secondary"
          onClick={async () => {
            await navigator.clipboard.writeText(address);
            setCopied(true);
          }}
        >
          Copy link
        </Button>
        <span role="status">{copied && "Copied."}</span>
      </p>
    </section>
  );
}
