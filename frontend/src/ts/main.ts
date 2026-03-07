import {
  renderAccount,
  renderAdmin,
  renderAuthCallback,
  renderClaimAccount,
  renderCompleteRegistration,
  renderHappyHour,
  renderLogin,
  renderMealbot,
  renderMealbotIndividualized,
  renderIndex,
} from "./pages.js";
import { ClaimFlags } from "./types.js";
import * as api from "./services/apiClient.js";

const pageMap: Record<string, () => Promise<void>> = {
  index: renderIndex,
  login: renderLogin,
  authCallback: renderAuthCallback,
  completeRegistration: renderCompleteRegistration,
  claimAccount: renderClaimAccount,
  account: renderAccount,
  mealbot: renderMealbot,
  mealbotIndividualized: renderMealbotIndividualized,
  happyHour: renderHappyHour,
  admin: renderAdmin,
};

/**
 * Update sidebar nav link visibility based on the user's authentication
 * state and permission claims.
 *
 * Links carry a `data-requires` attribute:
 *   - (none)       → always visible (public)
 *   - "auth"       → visible when authenticated
 *   - "guest"      → visible only when NOT authenticated
 *   - "ADMIN" etc. → visible when the user has that claim flag
 */
function updateNavVisibility(claims: number | null): void {
  const links = document.querySelectorAll<HTMLElement>("#sidebar-nav a[data-requires]");
  const isAuthenticated = claims !== null;

  links.forEach((link) => {
    const req = link.getAttribute("data-requires") ?? "";
    let visible = false;

    if (req === "auth") {
      visible = isAuthenticated;
    } else if (req === "guest") {
      visible = !isAuthenticated;
    } else if (req in ClaimFlags) {
      visible = isAuthenticated && (claims! & ClaimFlags[req]) !== 0;
    }

    if (visible) {
      link.classList.remove("nav-hidden");
    } else {
      link.classList.add("nav-hidden");
    }
  });
}

/** Wire the logout link to POST /api/v2/auth/logout then redirect to /login. */
function wireLogout(): void {
  const logoutLink = document.getElementById("nav-logout");
  if (!logoutLink) return;
  logoutLink.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      await api.postLogout();
    } catch { /* best-effort */ }
    window.location.href = "/login";
  });
}

async function bootstrap() {
  // Fetch the user's profile to determine nav visibility.
  // This silently fails for unauthenticated users (public pages).
  let claims: number | null = null;
  try {
    const profile = await api.getProfile();
    claims = profile.claims;
    // Apply server-side theme preference and sync to localStorage
    if (profile.theme && profile.theme !== "default") {
      document.documentElement.setAttribute("data-theme", profile.theme);
      localStorage.setItem("vibe-theme", profile.theme);
    } else if (profile.theme === "default") {
      document.documentElement.removeAttribute("data-theme");
      localStorage.removeItem("vibe-theme");
    }
  } catch { /* not authenticated — leave claims null */ }

  updateNavVisibility(claims);
  wireLogout();

  const path = window.location.pathname;
  const routeToPage: Record<string, string> = {
    "/": "index",
    "/happyhour": "happyHour",
    "/login": "login",
    "/auth/callback": "authCallback",
    "/auth/complete-registration": "completeRegistration",
    "/auth/claim-account": "claimAccount",
    "/account": "account",
    "/mealbot": "mealbot",
    "/mealbot/individualized": "mealbotIndividualized",

    "/admin": "admin",
  };

  const pageName = routeToPage[path];
  if (!pageName) {
    return;
  }
  await pageMap[pageName]();
}

void bootstrap().catch((err) => {
  console.error("[bootstrap] Unhandled error during page render:", err);
});
