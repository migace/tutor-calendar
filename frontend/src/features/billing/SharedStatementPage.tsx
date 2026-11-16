import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError, fetchSharedStatement } from "../../api/client";
import { Button, Notice, PageSkeleton } from "../../ui";
import { StatementTable } from "./StatementTable";

function tokenFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("token");
}

/**
 * Where a tutor's link for a parent leads: one student's lesson time, month by
 * month. Whoever has the link can read it; nothing can be changed from here.
 */
export function SharedStatementPage() {
  // The token stays in the fragment, which is never sent to a server, and is
  // carried along when moving between months.
  const [token] = useState(tokenFromFragment);
  const [params] = useSearchParams();
  const month = params.get("month");
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["shared-statement", token, month],
    queryFn: ({ signal }) => fetchSharedStatement(token!, month, signal),
    enabled: token !== null,
    placeholderData: keepPreviousData,
    retry: (failures, failure) => failures < 1 && !(failure instanceof ApiError),
  });

  if (token === null || (error instanceof ApiError && error.status === 401)) {
    return (
      <main className="page">
        <Notice tone="problem" level={1} title="This link does not lead to a statement">
          <p>Check that you copied the whole link, or ask the tutor for a new one.</p>
        </Notice>
      </main>
    );
  }
  if (isPending) {
    return (
      <main className="page">
        <PageSkeleton label="Loading the statement…" />
      </main>
    );
  }
  if (error) {
    return (
      <main className="page">
        <Notice tone="problem" level={1} title="We could not load the statement">
          <p>This is a problem on our side. Please try again.</p>
          <Button busy={isFetching} onClick={() => refetch()}>
            Try again
          </Button>
        </Notice>
      </main>
    );
  }

  return (
    <main className="page" aria-busy={isFetching}>
      <title>{`Lesson time with ${data.tutor_name}`}</title>
      <header className="page__header">
        <p className="page__eyebrow">Lesson time</p>
        <h1 className="page__title">{data.student_name ?? data.student_email}</h1>
        <p className="page__meta">
          Lessons with {data.tutor_name} · Dates on the tutor&rsquo;s calendar ({data.timezone})
        </p>
      </header>
      <StatementTable
        statement={data}
        monthLink={(first) => `?month=${first}${window.location.hash}`}
      />
    </main>
  );
}
