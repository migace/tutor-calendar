import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { fetchConfig, openDemoSession, requestSignInLink } from "../../api/client";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";
import { PROFILE_KEY, useProfile } from "./useProfile";

// Deliberately loose: something, an @, something with a dot. The server has the final say.
const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

export const CONFIG_KEY = ["config"] as const;

/** Whether this installation is a public demonstration. False until known. */
export function useDemoMode(): boolean {
  const { data } = useQuery({
    queryKey: CONFIG_KEY,
    queryFn: ({ signal }) => fetchConfig(signal),
    staleTime: Infinity,
    retry: false,
  });
  return data?.demo_mode ?? false;
}

export function SignInPage() {
  const all = useT();
  const t = all.signIn;
  const queryClient = useQueryClient();
  const profile = useProfile();
  const demoMode = useDemoMode();
  const input = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState<string>();
  const request = useMutation({ mutationFn: requestSignInLink });
  const demo = useMutation({
    mutationFn: openDemoSession,
    onSuccess: (tutor) => queryClient.setQueryData(PROFILE_KEY, tutor),
  });

  if (profile.isPending) {
    return (
      <main className="page" id="content">
        <PageSkeleton label={t.checking} />
      </main>
    );
  }
  if (profile.data) return <Navigate to="/panel" replace />;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim();
    if (!LOOKS_LIKE_EMAIL.test(address)) {
      setProblem(address ? t.emailInvalid : t.emailMissing);
      input.current?.focus();
      return;
    }
    setProblem(undefined);
    request.mutate(address);
  }

  if (request.isSuccess) {
    return (
      <main className="page" id="content">
        <Notice tone="success" level={1} title={t.checkEmailTitle} focusOnMount>
          <p>
            {t.checkEmailBefore} <strong>{request.variables}</strong> {t.checkEmailAfter}
          </p>
          <Button variant="secondary" onClick={() => request.reset()}>
            {t.useDifferent}
          </Button>
        </Notice>
      </main>
    );
  }

  return (
    <main className="page" id="content">
      <title>{t.pageTitle}</title>
      <header className="page__header">
        <p className="page__eyebrow">{t.eyebrow}</p>
        <h1 className="page__title">{t.title}</h1>
        <p className="page__meta">{t.intro}</p>
      </header>

      {demoMode && (
        <div className="notice notice--demo">
          <p>{all.demo.enterIntro}</p>
          {demo.isError && (
            <p className="form__error" role="alert">
              {all.demo.enterFailed}
            </p>
          )}
          <Button busy={demo.isPending} onClick={() => demo.mutate()}>
            {all.demo.enter}
          </Button>
        </div>
      )}

      <form className="form" noValidate onSubmit={handleSubmit}>
        <TextField
          ref={input}
          label={t.email}
          hint={t.emailHint}
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          error={problem}
          onChange={(event) => setEmail(event.target.value)}
        />
        {request.isError && (
          <p className="form__error" role="alert">
            {t.sendFailed}
          </p>
        )}
        <Button type="submit" wide variant={demoMode ? "secondary" : "primary"} busy={request.isPending}>
          {request.isPending ? t.sending : t.send}
        </Button>
      </form>
    </main>
  );
}
