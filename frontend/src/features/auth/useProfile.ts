import { useQuery } from "@tanstack/react-query";

import { fetchProfile } from "../../api/client";

export const PROFILE_KEY = ["profile"] as const;

/**
 * Who is signed in. `data` is the tutor, `null` when nobody is, and
 * `undefined` while the first answer is on its way.
 *
 * The session lives in a cookie that scripts cannot read, so asking the server
 * is the only way to know.
 */
export function useProfile() {
  return useQuery({
    queryKey: PROFILE_KEY,
    queryFn: ({ signal }) => fetchProfile(signal),
    staleTime: 5 * 60_000,
  });
}
