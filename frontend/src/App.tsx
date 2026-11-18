import { Link, Navigate, Route, Routes, useLocation, useParams } from "react-router";

import { SignInPage, useDemoMode } from "./features/auth/SignInPage";
import { VerifyPage } from "./features/auth/VerifyPage";
import { SharedStatementPage } from "./features/billing/SharedStatementPage";
import { StudentPage } from "./features/billing/StudentPage";
import { StudentsPage } from "./features/billing/StudentsPage";
import { BookingPage } from "./features/booking/BookingPage";
import { ManageBookingPage } from "./features/booking/ManageBookingPage";
import { AvailabilityPage } from "./features/panel/AvailabilityPage";
import { PanelLayout } from "./features/panel/PanelLayout";
import { SeriesPage } from "./features/panel/SeriesPage";
import { WeekPage } from "./features/panel/WeekPage";
import { SiteHeader } from "./features/frame/Frame";
import { useT } from "./i18n";
import { Notice } from "./ui";

function PublicBookingPage() {
  const { slug } = useParams();
  // Keyed by tutor, so moving between two booking pages starts each one afresh.
  return <BookingPage key={slug} slug={slug!} />;
}

function NotFound() {
  const t = useT().notFound;
  return (
    <main className="page" id="content">
      <title>{`${t.title} · Tutor Calendar`}</title>
      <Notice level={1} title={t.title}>
        <p>
          <Link className="link" to="/">
            {t.home}
          </Link>
        </p>
      </Notice>
    </main>
  );
}

/**
 * Lets keyboard users jump past the banner and navigation. It moves focus
 * instead of following its own link: several pages keep a token in the
 * address fragment, and "#content" would overwrite it.
 */
function SkipLink() {
  const t = useT().common;
  return (
    <a
      className="skip-link"
      href="#content"
      onClick={(event) => {
        event.preventDefault();
        const content = document.getElementById("content");
        content?.setAttribute("tabindex", "-1");
        content?.focus();
      }}
    >
      {t.skipToContent}
    </a>
  );
}

/** On a public demonstration: says so, and points to the other half of the product. */
function DemoBanner() {
  const t = useT().demo;
  const inPanel = useLocation().pathname.startsWith("/panel");
  if (!useDemoMode()) return null;
  return (
    <aside className="demo-banner">
      <p>
        <span className="demo-banner__badge" aria-hidden="true">
          Demo
        </span> {t.banner}{" "}
        <Link className="demo-banner__link" to={inPanel ? "/book/demo" : "/sign-in"}>
          {inPanel ? t.toBooking : t.toPanel}
        </Link>
      </p>
    </aside>
  );
}

export function App() {
  // The panel has a frame of its own, with the language switch in its sidebar.
  const inPanel = useLocation().pathname.startsWith("/panel");
  return (
    <>
      <SkipLink />
      <DemoBanner />
      {!inPanel && <SiteHeader />}
      <Routes>
        {/* Until tutors can sign up, the demo tutor's page doubles as the home page. */}
        <Route path="/" element={<Navigate to="/book/demo" replace />} />
        <Route path="/book/:slug" element={<PublicBookingPage />} />
        <Route path="/booking" element={<ManageBookingPage />} />
        <Route path="/statement" element={<SharedStatementPage />} />
        <Route path="/sign-in" element={<SignInPage />} />
        <Route path="/sign-in/verify" element={<VerifyPage />} />
        <Route path="/panel" element={<PanelLayout />}>
          <Route index element={<WeekPage />} />
          <Route path="regulars" element={<SeriesPage />} />
          <Route path="students" element={<StudentsPage />} />
          <Route path="students/:email" element={<StudentPage />} />
          <Route path="availability" element={<AvailabilityPage />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
