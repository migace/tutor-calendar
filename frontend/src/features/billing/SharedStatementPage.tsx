import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError, fetchSharedStatement } from "../../api/client";
import { useT } from "../../i18n";
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
  const all = useT();
  const t = all.statement;
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
      <main className="page" id="content">
        <Notice tone="problem" level={1} title={t.badLinkTitle}>
          <p>{t.badLinkBody}</p>
        </Notice>
      </main>
    );
  }
  if (isPending) {
    return (
      <main className="page" id="content">
        <PageSkeleton label={t.loading} />
      </main>
    );
  }
  if (error) {
    return (
      <main className="page" id="content">
        <Notice tone="problem" level={1} title={t.loadFailedTitle}>
          <p>{t.loadFailedBody}</p>
          <Button busy={isFetching} onClick={() => refetch()}>
            {all.common.tryAgain}
          </Button>
        </Notice>
      </main>
    );
  }

  return (
    <main className="page" id="content" aria-busy={isFetching}>
      <title>{t.pageTitle(data.tutor_name)}</title>
      <header className="page__header">
        <p className="page__eyebrow">{t.eyebrow}</p>
        <h1 className="page__title">{data.student_name ?? data.student_email}</h1>
        <p className="page__meta">{t.meta(data.tutor_name, data.timezone)}</p>
      </header>
      <StatementTable
        statement={data}
        monthLink={(first) => `?month=${first}${window.location.hash}`}
      />
    </main>
  );
}
