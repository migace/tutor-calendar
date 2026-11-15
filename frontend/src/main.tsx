import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { BookingPage } from "./features/booking/BookingPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Routing arrives with the tutor panel; until then there is one public page. */}
      <BookingPage slug="demo" />
    </QueryClientProvider>
  </StrictMode>,
);
