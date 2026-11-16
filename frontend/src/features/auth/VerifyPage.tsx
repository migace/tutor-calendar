import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router";

import { signIn } from "../../api/client";
import { useT } from "../../i18n";
import { Notice, PageSkeleton } from "../../ui";
import { PROFILE_KEY } from "./useProfile";

function tokenFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("token");
}

/**
 * Where a sign-in link lands. Trades the token in the address for a session.
 *
 * The token is single-use, so it must be sent exactly once even though React
 * runs effects twice in development. A query keyed by the token gives that for
 * free: however many times this component mounts, there is one request.
 */
export function VerifyPage() {
  const t = useT().signIn;
  const queryClient = useQueryClient();
  // Read once, then wipe it from the address bar and the browser history.
  const [token] = useState(tokenFromFragment);
  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const attempt = useQuery({
    queryKey: ["sign-in", token],
    queryFn: () => signIn(token!),
    enabled: token !== null,
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  useEffect(() => {
    if (attempt.data) queryClient.setQueryData(PROFILE_KEY, attempt.data);
  }, [attempt.data, queryClient]);

  if (attempt.data) return <Navigate to="/panel" replace />;

  if (token === null || attempt.isError) {
    return (
      <main className="page" id="content">
        <Notice tone="problem" level={1} title={t.deadLinkTitle}>
          <p>{t.deadLinkBody}</p>
          <p>
            <Link className="link" to="/sign-in">
              {t.newLink}
            </Link>
          </p>
        </Notice>
      </main>
    );
  }

  return (
    <main className="page" id="content">
      <PageSkeleton label={t.signingIn} />
    </main>
  );
}
