import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, NavLink, Outlet, useOutletContext } from "react-router";

import { signOut, type Profile } from "../../api/client";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
import { PROFILE_KEY, useProfile } from "../auth/useProfile";

/** The signed-in tutor, for pages rendered inside the panel. */
export function useTutor(): Profile {
  return useOutletContext<Profile>();
}

/**
 * The frame around every panel page, and the gate in front of them: without a
 * session the visitor is sent to sign in. The server enforces the same rule on
 * every request; this only saves showing a page that could not load anything.
 */
export function PanelLayout() {
  const all = useT();
  const t = all.panel;
  const queryClient = useQueryClient();
  const profile = useProfile();
  const leave = useMutation({
    mutationFn: signOut,
    onSuccess: () => {
      // Forget everything that was loaded for this tutor, then show "signed out".
      queryClient.clear();
      queryClient.setQueryData(PROFILE_KEY, null);
    },
  });

  if (profile.isPending) {
    return (
      <main className="page page--wide" id="content">
        <PageSkeleton label={t.loading} />
      </main>
    );
  }
  if (profile.isError) {
    return (
      <main className="page page--wide" id="content">
        <Notice tone="problem" level={1} title={t.loadFailedTitle}>
          <p>{t.loadFailedBody}</p>
          <Button busy={profile.isFetching} onClick={() => profile.refetch()}>
            {all.common.tryAgain}
          </Button>
        </Notice>
      </main>
    );
  }
  if (!profile.data) return <Navigate to="/sign-in" replace />;

  const tutor = profile.data;
  return (
    <div className="page page--wide">
      <header className="panel-header">
        <div>
          <p className="page__eyebrow">{t.eyebrow}</p>
          <p className="panel-header__name">{tutor.display_name}</p>
        </div>
        <nav className="panel-nav" aria-label={t.nav}>
          <NavLink className="panel-nav__link" to="/panel" end>
            {t.week}
          </NavLink>
          <NavLink className="panel-nav__link" to="/panel/regulars">
            {t.regulars}
          </NavLink>
          <NavLink className="panel-nav__link" to="/panel/students">
            {t.students}
          </NavLink>
          <NavLink className="panel-nav__link" to="/panel/availability">
            {t.availability}
          </NavLink>
          <Link className="panel-nav__link" to={`/book/${tutor.slug}`}>
            {t.bookingPage}
          </Link>
          <Button variant="secondary" busy={leave.isPending} onClick={() => leave.mutate()}>
            {t.signOut}
          </Button>
        </nav>
      </header>
      {leave.isError && (
        <p className="form__error" role="alert">
          {t.signOutFailed}
        </p>
      )}
      <main id="content">
        <Outlet context={tutor} />
      </main>
    </div>
  );
}
