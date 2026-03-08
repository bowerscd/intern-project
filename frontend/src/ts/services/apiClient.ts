/**
 * Typed API client for the vibe-coded FastAPI backend.
 * All calls use fetch with credentials: "include" for session cookies.
 */

const API_BASE = (window as any).__API_BASE ?? "http://localhost:8000";

/**
 * In direct-API mode (API_BASE is an absolute URL pointing to a different
 * origin), qualify a relative redirect path with the frontend's own origin
 * so the backend redirects to the frontend after OIDC, not to itself.
 * In proxy mode (API_BASE is empty / same origin), leave the path relative.
 */
function qualifyRedirect(path: string): string {
  if (API_BASE) return `${window.location.origin}${path}`;
  return path;
}

// ── CSRF Token Management ─────────────────────────────────────────────

let _csrfToken: string | null = null;

/**
 * Fetch a CSRF token from the backend and cache it.
 * Uses a raw fetch to avoid circular dependency with request().
 */
async function fetchCsrfToken(): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v2/auth/csrf-token`, {
      method: "GET",
      credentials: "include",
    });
    if (res.ok) {
      const data = await res.json();
      _csrfToken = data.csrf_token;
      return _csrfToken;
    }
  } catch {
    /* CSRF token fetch failed — mutating requests may fail with 403 */
  }
  return null;
}

// ── Core Request Helper ───────────────────────────────────────────────

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  // Include CSRF token on state-changing requests
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    if (!_csrfToken) await fetchCsrfToken();
    if (_csrfToken) headers["X-CSRF-Token"] = _csrfToken;
  }

  const opts: RequestInit = { method, credentials: "include", headers };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    // Reset cached CSRF token on 403 so it's re-fetched on next attempt
    if (res.status === 403 && text.includes("CSRF")) {
      _csrfToken = null;
    }
    // Extract a user-friendly message from the backend JSON error response.
    // Never expose raw JSON bodies (which may contain tracebacks, internal
    // paths, or validation internals) to the end user.
    let userMessage: string;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed.detail === "string") {
        userMessage = parsed.detail;
      } else if (Array.isArray(parsed.detail)) {
        // Pydantic validation errors — show only the human-readable messages
        userMessage = parsed.detail
          .map((e: { msg?: string }) => e.msg ?? "Validation error")
          .join("; ");
      } else {
        userMessage = `Request failed (${res.status})`;
      }
    } catch {
      userMessage = text.slice(0, 200) || `Request failed (${res.status})`;
    }
    throw new Error(userMessage);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function get<T>(path: string): Promise<T> { return request<T>("GET", path); }
function post<T>(path: string, body?: unknown): Promise<T> { return request<T>("POST", path, body); }
function patch<T>(path: string, body?: unknown): Promise<T> { return request<T>("PATCH", path, body); }
function del<T>(path: string): Promise<T> { return request<T>("DELETE", path); }

// ── Auth ──────────────────────────────────────────────────────────────

/** POST /api/v2/auth/logout — destroy the backend session. */
export function postLogout(): Promise<void> {
  return post("/api/v2/auth/logout");
}

// ── Pagination ────────────────────────────────────────────────────────

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

/**
 * Fetch all pages of a paginated endpoint and return the concatenated items.
 * Useful for endpoints that now return PaginatedResponse but the caller
 * needs the full dataset (e.g. for client-side infinite scroll).
 */
async function fetchAllPages<T>(basePath: string, pageSize: number = 100): Promise<T[]> {
  const all: T[] = [];
  let page = 1;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const sep = basePath.includes("?") ? "&" : "?";
    const resp = await get<PaginatedResponse<T>>(`${basePath}${sep}page=${page}&page_size=${pageSize}`);
    all.push(...resp.items);
    if (all.length >= resp.total || resp.items.length < pageSize) break;
    page++;
  }
  return all;
}

// ── Auth ──────────────────────────────────────────────────────────────

/** Returns the URL to redirect to for OIDC login. */
export function loginUrl(provider: string, redirect?: string): string {
  const params = new URLSearchParams();
  if (redirect) params.set("redirect", qualifyRedirect(redirect));
  return `${API_BASE}/api/v2/auth/login/${provider}?${params}`;
}

/** Returns the URL to redirect to for OIDC registration. */
export function registerUrl(provider: string, redirect?: string): string {
  const params = new URLSearchParams();
  if (redirect) params.set("redirect", qualifyRedirect(redirect));
  return `${API_BASE}/api/v2/auth/register/${provider}?${params}`;
}

export type CompleteRegistrationRequest = { username: string };
export type CompleteRegistrationResponse = { id: number; username: string; status?: string; message?: string };

export function completeRegistration(body: CompleteRegistrationRequest): Promise<CompleteRegistrationResponse> {
  return post("/api/v2/auth/complete-registration", body);
}

export type ClaimAccountRequest = { username: string };
export type ClaimAccountResponse = { claim_id: number; status: string; message: string };

export function getClaimableAccounts(): Promise<string[]> {
  return get("/api/v2/auth/claimable-accounts");
}

export function claimAccount(body: ClaimAccountRequest): Promise<ClaimAccountResponse> {
  return post("/api/v2/auth/claim-account", body);
}

// ── Account ───────────────────────────────────────────────────────────

export type ProfileResponse = {
  id: number;
  username: string;
  oidc_email: string | null;
  email: string | null;
  phone: string | null;
  phone_provider: string;
  claims: number;
  theme: string;
  status: string;
};

export type ProfileUpdate = {
  username?: string;
  email?: string;
  phone?: string;
  phone_provider?: string;
};

export type ClaimsUpdate = {
  add?: string[];
  remove?: string[];
};

export function getProfile(): Promise<ProfileResponse> {
  return get("/api/v2/account/profile");
}

export function getPhoneProviders(): Promise<string[]> {
  return get("/api/v2/account/phone-providers");
}

export function updateProfile(body: ProfileUpdate): Promise<ProfileResponse> {
  return patch("/api/v2/account/profile", body);
}

export function updateClaims(body: ClaimsUpdate): Promise<ProfileResponse> {
  return patch("/api/v2/account/claims", body);
}

// ── Mealbot ───────────────────────────────────────────────────────────

export type RecordResponse = {
  id: number;
  payer: string;
  recipient: string;
  credits: number;
  date: string;
};

export type CreateRecordRequest = {
  payer: string;
  recipient: string;
  credits: number;
};

export type SummaryResponse = Record<string, Record<string, { "incoming-credits": number; "outgoing-credits": number }>>;

export function getMealbotLedger(): Promise<RecordResponse[]> {
  return fetchAllPages<RecordResponse>("/api/v2/mealbot/ledger");
}

export function getMyMealbotLedger(): Promise<RecordResponse[]> {
  return fetchAllPages<RecordResponse>("/api/v2/mealbot/ledger/me");
}

export function getMealbotLedgerPage(page?: number, pageSize?: number): Promise<PaginatedResponse<RecordResponse>> {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const q = params.toString() ? `?${params}` : "";
  return get(`/api/v2/mealbot/ledger${q}`);
}

export function getMyMealbotLedgerPage(page?: number, pageSize?: number): Promise<PaginatedResponse<RecordResponse>> {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const q = params.toString() ? `?${params}` : "";
  return get(`/api/v2/mealbot/ledger/me${q}`);
}

export function getMealbotSummary(user?: string, start?: string, end?: string): Promise<SummaryResponse> {
  const params = new URLSearchParams();
  if (user) params.set("user", user);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const q = params.toString() ? `?${params}` : "";
  return get(`/api/v2/mealbot/summary${q}`);
}

export function createMealbotRecord(body: CreateRecordRequest): Promise<{ status: string }> {
  return post("/api/v2/mealbot/record", body);
}

export function voidMealbotRecord(recordId: number): Promise<{ status: string; record_id: number }> {
  return del(`/api/v2/mealbot/record/${recordId}`);
}

// ── Happy Hour ────────────────────────────────────────────────────────

export type EventResponse = {
  id: number;
  description: string | null;
  when: string;
  location_id: number;
  location_name: string;
  tyrant_username: string | null;
  auto_selected: boolean;
  current_tyrant_username: string | null;
  current_tyrant_deadline: string | null;
};

export type EventCreate = {
  location_id: number;
  description?: string;
  when: string;
};

export type EventUpdate = {
  location_id?: number;
  description?: string;
  when?: string;
};

export type LocationResponse = {
  id: number;
  name: string;
  closed: boolean;
  illegal: boolean;
  url: string | null;
  address_raw: string;
  number: number;
  street_name: string;
  city: string;
  state: string;
  zip_code: string;
  latitude: number;
  longitude: number;
};

export type LocationCreate = {
  name: string;
  url?: string;
  address_raw: string;
  number: number;
  street_name: string;
  city: string;
  state: string;
  zip_code: string;
  latitude: number;
  longitude: number;
};

export type LocationUpdate = Partial<LocationCreate> & { closed?: boolean; illegal?: boolean };

export type RotationMemberResponse = {
  position: number;
  username: string;
  status: string;
  deadline: string | null;
};

export type RotationScheduleResponse = {
  cycle: number;
  members: RotationMemberResponse[];
};

export function getEvents(): Promise<EventResponse[]> {
  return fetchAllPages<EventResponse>("/api/v2/happyhour/events");
}

export function getEventsPage(page?: number, pageSize?: number): Promise<PaginatedResponse<EventResponse>> {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const q = params.toString() ? `?${params}` : "";
  return get(`/api/v2/happyhour/events${q}`);
}

export function getUpcomingEvent(): Promise<EventResponse | null> {
  return get("/api/v2/happyhour/events/upcoming");
}

export function createEvent(body: EventCreate): Promise<EventResponse> {
  return post("/api/v2/happyhour/events", body);
}

export function updateEvent(id: number, body: EventUpdate): Promise<EventResponse> {
  return patch(`/api/v2/happyhour/events/${id}`, body);
}

export function cancelEvent(id: number): Promise<{ status: string; event_id: number }> {
  return del(`/api/v2/happyhour/events/${id}`);
}

export function skipRotationTurn(): Promise<{ status: string; skipped_user: string; next_user: string | null }> {
  return post("/api/v2/happyhour/rotation/skip");
}

export function getRotation(): Promise<RotationScheduleResponse> {
  return get("/api/v2/happyhour/rotation");
}

export function getLocations(): Promise<LocationResponse[]> {
  return fetchAllPages<LocationResponse>("/api/v2/happyhour/locations");
}

export function getLocationsPage(page?: number, pageSize?: number): Promise<PaginatedResponse<LocationResponse>> {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const q = params.toString() ? `?${params}` : "";
  return get(`/api/v2/happyhour/locations${q}`);
}

export function createLocation(body: LocationCreate): Promise<LocationResponse> {
  return post("/api/v2/happyhour/locations", body);
}

export function getRandomLocation(weighted = false): Promise<LocationResponse> {
  const q = weighted ? "?weighted=true" : "";
  return get(`/api/v2/happyhour/locations/random${q}`);
}

export function updateLocation(id: number, body: LocationUpdate): Promise<LocationResponse> {
  return patch(`/api/v2/happyhour/locations/${id}`, body);
}

// ── Admin ─────────────────────────────────────────────────────────────

export type ClaimRequestResponse = {
  id: number;
  requester_provider: string;
  requester_external_id: string;
  requester_name: string;
  requester_email: string | null;
  target_account_id: number;
  target_username: string;
  status: string;
  created_at: string | null;
  resolved_at: string | null;
};

export type ClaimReviewRequest = { decision: "approve" | "deny" };

export function getClaimRequests(includeResolved = false): Promise<ClaimRequestResponse[]> {
  const q = includeResolved ? "?include_resolved=true" : "";
  return get(`/api/v2/account/admin/claims${q}`);
}

export function reviewClaimRequest(claimId: number, body: ClaimReviewRequest): Promise<ClaimRequestResponse> {
  return post(`/api/v2/account/admin/claims/${claimId}/review`, body);
}

// ── Admin Account Management ──────────────────────────────────────────

export type AdminAccountResponse = {
  id: number;
  username: string;
  email: string | null;
  status: string;
  claims: number;
  provider: string;
};

export type AdminStatusUpdateRequest = { status: string };
export type AdminRoleUpdateRequest = { grant_admin: boolean };

export function getAdminAccounts(statusFilter?: string): Promise<AdminAccountResponse[]> {
  const q = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return get(`/api/v2/account/admin/accounts${q}`);
}

export function updateAccountStatus(accountId: number, body: AdminStatusUpdateRequest): Promise<AdminAccountResponse> {
  return post(`/api/v2/account/admin/accounts/${accountId}/status`, body);
}

export function updateAccountRole(accountId: number, body: AdminRoleUpdateRequest): Promise<AdminAccountResponse> {
  return post(`/api/v2/account/admin/accounts/${accountId}/role`, body);
}

// ── Theme ─────────────────────────────────────────────────────────────

export function getThemes(): Promise<string[]> {
  return get("/api/v2/account/themes");
}

export function setTheme(theme: string): Promise<{ status: string; theme: string }> {
  return request<{ status: string; theme: string }>("PUT", "/api/v2/account/theme", { theme });
}
