import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, NavLink, Outlet, useOutletContext } from "react-router";

import { signOut, type Profile } from "../../api/client";
import { useT } from "../../i18n";
import { Button, Notice, PageSkeleton } from "../../ui";
import { Brand, LanguageSwitch, SiteHeader } from "../frame/Frame";
import {
  CalendarIcon,
  ClockIcon,
  OpenIcon,
  PeopleIcon,
  RepeatIcon,
  SignOutIcon,
} from "../frame/icons";
import { PROFILE_KEY, useProfile } from "../auth/useProfile";

/** "Anna Nowak" → "AN": a face for a name, where there are no photos. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? [words[0]!, words.at(-1)!] : words;
  return letters.map((word) => word[0]!.toLocaleUpperCase()).join("");
}

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
      <>
        <SiteHeader />
        <main className="page page--wide" id="content">
          <PageSkeleton label={t.loading} />
        </main>
      </>
    );
  }
  if (profile.isError) {
    return (
      <>
        <SiteHeader />
        <main className="page page--wide" id="content">
          <Notice tone="problem" level={1} title={t.loadFailedTitle}>
            <p>{t.loadFailedBody}</p>
            <Button busy={profile.isFetching} onClick={() => profile.refetch()}>
              {all.common.tryAgain}
            </Button>
          </Notice>
        </main>
      </>
    );
  }
  if (!profile.data) return <Navigate to="/sign-in" replace />;

  const tutor = profile.data;
  const sections = [
    { to: "/panel", name: t.week, icon: <CalendarIcon />, end: true },
    { to: "/panel/regulars", name: t.regulars, icon: <RepeatIcon />, end: false },
    { to: "/panel/students", name: t.students, icon: <PeopleIcon />, end: false },
    { to: "/panel/availability", name: t.availability, icon: <ClockIcon />, end: false },
  ];
  return (
    // On a phone the sidebar comes apart: the name on top, the sections in a
    // bar along the bottom, the rest after the page.
    <div className="shell">
      <div className="shell__side">
        <header className="shell__top">
          <Brand />
        </header>
        <nav className="shell__nav" aria-label={t.nav}>
          {sections.map((section) => (
            <NavLink key={section.to} className="shell__link" to={section.to} end={section.end}>
              {section.icon}
              <span>{section.name}</span>
            </NavLink>
          ))}
        </nav>
        <footer className="shell__extra">
          <Link className="shell__link shell__link--quiet" to={`/book/${tutor.slug}`}>
            <OpenIcon />
            <span>{t.bookingPage}</span>
          </Link>
          <button
            type="button"
            className="shell__link shell__link--quiet"
            disabled={leave.isPending}
            aria-busy={leave.isPending || undefined}
            onClick={() => leave.mutate()}
          >
            <SignOutIcon />
            <span>{t.signOut}</span>
          </button>
          <LanguageSwitch />
          <div className="shell__user">
            <span className="avatar" aria-hidden="true">
              {initials(tutor.display_name)}
            </span>
            <span className="shell__name">
              <span className="shell__eyebrow">{t.eyebrow}</span>
              {tutor.display_name}
            </span>
          </div>
          {leave.isError && (
            <p className="form__error" role="alert">
              {t.signOutFailed}
            </p>
          )}
        </footer>
      </div>
      <main className="shell__main" id="content">
        <div className="shell__page">
          <Outlet context={tutor} />
        </div>
      </main>
    </div>
  );
}
