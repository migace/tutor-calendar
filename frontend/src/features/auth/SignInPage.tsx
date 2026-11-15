import { useMutation } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { requestSignInLink } from "../../api/client";
import { Button, Notice, PageSkeleton, TextField } from "../../ui";
import { useProfile } from "./useProfile";

// Deliberately loose: something, an @, something with a dot. The server has the final say.
const LOOKS_LIKE_EMAIL = /^\S+@\S+\.\S+$/;

export function SignInPage() {
  const profile = useProfile();
  const input = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState<string>();
  const request = useMutation({ mutationFn: requestSignInLink });

  if (profile.isPending) {
    return (
      <main className="page">
        <PageSkeleton label="Checking whether you are signed in…" />
      </main>
    );
  }
  if (profile.data) return <Navigate to="/panel" replace />;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim();
    if (!LOOKS_LIKE_EMAIL.test(address)) {
      setProblem(
        address ? "Enter an email address like name@example.com." : "Enter your email address.",
      );
      input.current?.focus();
      return;
    }
    setProblem(undefined);
    request.mutate(address);
  }

  if (request.isSuccess) {
    return (
      <main className="page">
        <Notice tone="success" level={1} title="Check your email" focusOnMount>
          <p>
            If <strong>{request.variables}</strong> belongs to a tutor, a sign-in link is on its
            way. It works once and expires in 15 minutes.
          </p>
          <Button variant="secondary" onClick={() => request.reset()}>
            Use a different address
          </Button>
        </Notice>
      </main>
    );
  }

  return (
    <main className="page">
      <title>Sign in · Tutor Calendar</title>
      <header className="page__header">
        <p className="page__eyebrow">Tutor panel</p>
        <h1 className="page__title">Sign in</h1>
        <p className="page__meta">
          No password to remember: we email you a link that signs you in.
        </p>
      </header>

      <form className="form" noValidate onSubmit={handleSubmit}>
        <TextField
          ref={input}
          label="Email address"
          hint="The address your tutor account was set up with."
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
            We could not send the link. Please try again.
          </p>
        )}
        <Button type="submit" wide busy={request.isPending}>
          {request.isPending ? "Sending…" : "Email me a sign-in link"}
        </Button>
      </form>
    </main>
  );
}
