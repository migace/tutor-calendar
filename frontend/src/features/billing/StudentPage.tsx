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
import { formatDay, formatMinutes } from "../../dates";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";
import { initials } from "../panel/PanelLayout";
import { StatementTable } from "./StatementTable";
import { ACCOUNTS_KEY } from "./StudentsPage";

/** One student's account, as their tutor sees it: the statement, and a way to add to it. */
export function StudentPage() {
  const all = useT();
  const t = all.student;
  const studentId = useParams().studentId!;
  const [params] = useSearchParams();
  const month = params.get("month");
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["statement", studentId, month],
    queryFn: ({ signal }) => fetchStatement(studentId, month, signal),
    placeholderData: keepPreviousData,
    retry: (failures, failure) => failures < 1 && !(failure instanceof ApiError),
  });

  const back = (
    <p className="back">
      <Link className="back__link" to="/panel/students">
        <span aria-hidden="true">←</span> {t.all}
      </Link>
    </p>
  );

  if (isPending) return <PageSkeleton label={t.loading} />;
  // 404 for an id that is nobody's, 422 for something that is not an id at
  // all, such as an address left over from an old bookmark.
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return (
      <div className="regulars">
        <title>{t.pageTitle(t.missingTitle)}</title>
        <header className="page-head">{back}</header>
        <Notice tone="problem" level={1} title={t.missingTitle}>
          <p>{t.missingBody}</p>
        </Notice>
      </div>
    );
  }
  if (error) {
    return (
      <Notice tone="problem" title={t.loadFailedTitle}>
        <Button busy={isFetching} onClick={() => refetch()}>
          {all.common.tryAgain}
        </Button>
      </Notice>
    );
  }

  if (data.nothing_recorded) {
    // Not a dead end: a tutor often sells a package before the first lesson,
    // and recording it is what puts the student on the list.
    return (
      <div className="regulars">
        <title>{t.pageTitle(data.student_email)}</title>
        <header className="page-head">
          {back}
          <h1 className="week-bar__title">{data.student_email}</h1>
        </header>
        <Notice title={t.nothingTitle}>
          <p>{t.nothingBody}</p>
        </Notice>
        <AddTime studentId={studentId} />
      </div>
    );
  }

  const name = data.student_name ?? data.student_email;
  const owes = data.balance_minutes < 0;
  const used = data.entries
    .filter((entry) => entry.kind === "lesson" && entry.minutes < 0)
    .reduce((sum, entry) => sum - entry.minutes, 0);
  return (
    <div className="account-page" aria-busy={isFetching}>
      <title>{t.pageTitle(name)}</title>
      <header className="page-head">
        {back}
        <div className="page-head__who">
          <span className="avatar avatar--large" aria-hidden="true">
            {initials(name)}
          </span>
          <div>
            <h1 className="week-bar__title">{name}</h1>
            {data.student_name && <p className="page__meta">{data.student_email}</p>}
          </div>
        </div>
      </header>

      <dl className="tiles" aria-label={t.tiles}>
        <div className={`tile${owes ? " tile--owed" : ""}`}>
          <dt>{owes ? t.tileOwed : t.tileLeft}</dt>
          <dd>{formatMinutes(Math.abs(data.balance_minutes))}</dd>
        </div>
        <div className="tile">
          <dt>{t.tileUsed(formatDay(data.month, { month: "long" }))}</dt>
          <dd>{formatMinutes(used)}</dd>
        </div>
      </dl>

      <div className="account-page__columns">
        <StatementTable statement={data} monthLink={(first) => `?month=${first}`} />
        <div className="account-page__side">
          <AddTime studentId={studentId} />
          <ParentLink statement={data} />
        </div>
      </div>
    </div>
  );
}

type Kind = NewEntry["kind"];

function AddTime({ studentId }: { studentId: string }) {
  const t = useT().student;
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
      return recordEntry(studentId, attempt.current.id, entry);
    },
    onSuccess: () => {
      // The next entry is a new one even if it looks the same: ten hours twice
      // is two packages.
      attempt.current = null;
      setHours("");
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["statement", studentId] });
      void queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY });
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // A decimal comma is how hours are written in much of Europe.
    const minutes = Math.round(Number(hours.replace(",", ".")) * 60);
    const found: typeof problems = {};
    if (!hours.trim() || !Number.isFinite(minutes) || minutes === 0) {
      found.hours = t.hoursInvalid;
    } else if (kind === "purchase" && minutes < 0) {
      found.hours = t.packageNegative;
    }
    if (kind === "adjustment" && !note.trim()) found.note = t.reasonMissing;
    setProblems(found);
    if (found.hours) return hoursInput.current?.focus();
    if (found.note) return noteInput.current?.focus();
    record.mutate({ kind, minutes, note: note.trim() });
  }

  const edited = () => record.reset();
  const kinds = [
    ["purchase", t.kindPackage],
    ["adjustment", t.kindCorrection],
  ] as const;

  return (
    <section className="card" aria-labelledby="add-time-heading">
      <h2 className="step__heading" id="add-time-heading">
        {t.addHeading}
      </h2>
      <form className="form" noValidate onSubmit={handleSubmit}>
        <fieldset className="choice">
          <legend className="field__label">{t.what}</legend>
          {kinds.map(([value, label]) => (
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
          label={t.hours}
          hint={kind === "purchase" ? t.hoursHintPackage : t.hoursHintCorrection}
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
          label={kind === "purchase" ? t.noteOptional : t.reason}
          hint={t.noteHint}
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
        <p className="page__meta">{t.permanent}</p>
        {record.isError && (
          <p className="form__error" role="alert">
            {record.error instanceof ApiError && record.error.status === 422
              ? t.refused(record.error.detail)
              : t.failed}
          </p>
        )}
        <p className="hours__status" role="status">
          {record.isSuccess &&
            t.recorded(
              `${record.data.minutes > 0 ? "+" : ""}${formatMinutes(record.data.minutes)}`,
            )}
        </p>
        <Button type="submit" busy={record.isPending}>
          {record.isPending ? t.submitting : t.submit}
        </Button>
      </form>
    </section>
  );
}

function ParentLink({ statement }: { statement: Statement }) {
  const t = useT().student;
  const [copied, setCopied] = useState(false);
  if (!statement.share_token) return null;
  // In the fragment, which browsers do not send to servers.
  const path = `/statement#token=${statement.share_token}`;
  const address = `${window.location.origin}${path}`;

  return (
    <section className="card" aria-labelledby="parent-link-heading">
      <h2 className="step__heading" id="parent-link-heading">
        {t.parentHeading}
      </h2>
      <p className="page__meta">{t.parentIntro}</p>
      <p className="share">
        <Link className="link" to={path}>
          {t.openParent}
        </Link>
        <Button
          variant="secondary"
          onClick={async () => {
            await navigator.clipboard.writeText(address);
            setCopied(true);
          }}
        >
          {t.copy}
        </Button>
        <span role="status">{copied && t.copied}</span>
      </p>
    </section>
  );
}
