const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }

  return res.json();
}

export async function login(password: string): Promise<string> {
  const data = await fetchApi<{ access_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  localStorage.setItem("token", data.access_token);
  return data.access_token;
}

export function logout() {
  localStorage.removeItem("token");
  window.location.href = "/login";
}

export function isLoggedIn(): boolean {
  return typeof window !== "undefined" && !!localStorage.getItem("token");
}

/** SWR-compatible fetcher — use as: useSWR("/api/stats", fetcher<Stats>) */
export function fetcher<T>(url: string): Promise<T> {
  return fetchApi<T>(url);
}
