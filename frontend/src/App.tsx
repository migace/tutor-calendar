import { Link, Navigate, Route, Routes, useParams } from "react-router";

import { SignInPage } from "./features/auth/SignInPage";
import { VerifyPage } from "./features/auth/VerifyPage";
import { BookingPage } from "./features/booking/BookingPage";
import { AvailabilityPage } from "./features/panel/AvailabilityPage";
import { PanelLayout } from "./features/panel/PanelLayout";
import { WeekPage } from "./features/panel/WeekPage";
import { Notice } from "./ui";

function PublicBookingPage() {
  const { slug } = useParams();
  // Keyed by tutor, so moving between two booking pages starts each one afresh.
  return <BookingPage key={slug} slug={slug!} />;
}

function NotFound() {
  return (
    <main className="page">
      <Notice level={1} title="There is nothing at this address">
        <p>
          <Link className="link" to="/">
            Go to the demo booking page
          </Link>
        </p>
      </Notice>
    </main>
  );
}

export function App() {
  return (
    <Routes>
      {/* Until tutors can sign up, the demo tutor's page doubles as the home page. */}
      <Route path="/" element={<Navigate to="/book/demo" replace />} />
      <Route path="/book/:slug" element={<PublicBookingPage />} />
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/sign-in/verify" element={<VerifyPage />} />
      <Route path="/panel" element={<PanelLayout />}>
        <Route index element={<WeekPage />} />
        <Route path="availability" element={<AvailabilityPage />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
