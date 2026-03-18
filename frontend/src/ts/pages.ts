import { byId, esc, status, table, formatDate, formatDateShort, setupInfiniteScroll, setupServerPaginatedScroll, appendTableRows } from "./utils.js";
import { dataProvider } from "./services/dataProvider.js";
import { decodeClaims } from "./types.js";
import * as api from "./services/apiClient.js";

/** Best-effort parsing of a US-style address string into structured fields. */
function parseAddress(raw: string): { number: number; street_name: string; city: string; state: string; zip_code: string; latitude: number; longitude: number } {
  // Expected format: "123 Main St, Austin, TX 78701"
  const parts = raw.split(",").map(s => s.trim());
  let number = 0, street_name = "", city = "", state = "", zip_code = "";
  if (parts.length >= 1) {
    const m = parts[0].match(/^(\d+)\s+(.+)$/);
    if (m) { number = parseInt(m[1]); street_name = m[2]; }
    else { street_name = parts[0]; }
  }
  if (parts.length >= 2) city = parts[1];
  if (parts.length >= 3) {
    const stateZip = parts[2].match(/^([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)?$/);
    if (stateZip) { state = stateZip[1].toUpperCase(); zip_code = stateZip[2] ?? ""; }
    else { state = parts[2]; }
  }
  return { number, street_name, city, state, zip_code, latitude: 0, longitude: 0 };
}

export async function renderIndex() {
  // Static welcome page, no dynamic content needed
}

export async function renderLogin() {
  const devMode = (window as any).__DEV_MODE === true;

  // Check for error message from OIDC callback redirect
  const urlParams = new URLSearchParams(window.location.search);
  const errorMsg = urlParams.get("error");
  let errorHtml = "";
  if (errorMsg) {
    errorHtml = `<div class="card" style="background: #3a1a1a; border: 1px solid #c44; padding: 16px; margin-bottom: 16px;">
      <p style="color: #faa; margin: 0;"><strong>Login failed:</strong> ${esc(errorMsg)}</p>
    </div>`;
  }

  let html = errorHtml + `
    <p><a href="${esc(api.loginUrl("google", "/account"))}">Login with Google</a></p>
    <p><a href="${esc(api.registerUrl("google", "/auth/complete-registration"))}">Register with Google</a></p>
  `;
  if (devMode) {
    html += `
      <hr style="margin: 16px 0; border-color: #444;" />
      <p style="color: #aaa; font-size: 0.9em;">Dev-only (mock OIDC provider)</p>
      <p><a href="${esc(api.loginUrl("test", "/account"))}">Login with Test Provider</a></p>
      <p><a href="${esc(api.registerUrl("test", "/auth/complete-registration"))}">Register with Test Provider</a></p>
    `;
  }
  byId("login-actions").innerHTML = html;
}

export async function renderAuthCallback() {
  byId("auth-callback-status").innerHTML = status("Processing authentication...");
  // The real callback is handled server-side by the backend.
  // If the user lands here, the OIDC flow redirect should have already set the session.
  try {
    const profile = await dataProvider.getProfile();
    byId("auth-callback-status").innerHTML = status(`Logged in as ${profile.username}. Redirecting...`);
    setTimeout(() => { window.location.href = "/account"; }, 1500);
  } catch {
    byId("auth-callback-status").innerHTML = status("Authentication pending. You may need to complete registration.");
  }
}

export async function renderCompleteRegistration() {
  const form = byId<HTMLFormElement>("complete-registration-form");
  const result = byId("complete-registration-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = (byId("username") as HTMLInputElement).value.trim();
    if (!username) { result.innerHTML = status("Username is required."); return; }
    try {
      const res = await api.completeRegistration({ username });
      if (res.status === "pending_approval") {
        result.innerHTML = status("Your account has been created and is awaiting admin approval. You will be able to log in once an admin approves your account.");
      } else {
        result.innerHTML = status(`Registration complete! Welcome, ${res.username}.`);
        setTimeout(() => { window.location.href = "/account"; }, 1500);
      }
    } catch (err: any) {
      result.innerHTML = status(`Error: ${err.message}`);
    }
  });

  // Dynamically render the claim section only if there are claimable accounts.
  try {
    const claimable = await api.getClaimableAccounts();
    const claimSection = document.getElementById("claim-section");
    if (claimable.length > 0 && claimSection) {
      claimSection.innerHTML = `
        <section class="card" style="margin-top: 1rem;">
          <h3>Have an existing account?</h3>
          <p style="color: #aaa; margin-bottom: 0.75rem;">
            If you had an account before this site moved to the new login system,
            you can link your login to it instead of creating a new one.
          </p>
          <form id="claim-account-form">
            <label for="claim-username">Existing Username</label>
            <input id="claim-username" name="username" placeholder="legacy.user" />
            <button type="submit">Claim Account</button>
          </form>
          <div id="claim-account-result"></div>
        </section>`;
      byId<HTMLFormElement>("claim-account-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const username = (byId("claim-username") as HTMLInputElement).value.trim();
        const claimResult = byId("claim-account-result");
        if (!username) { claimResult.innerHTML = status("Username is required."); return; }
        try {
          const res = await api.claimAccount({ username });
          claimResult.innerHTML = status(res.message || "Claim submitted for admin review.");
        } catch (err: any) {
          claimResult.innerHTML = status(`Error: ${err.message}`);
        }
      });
    }
  } catch (err) {
    console.error("[claim section] failed to load claimable accounts:", err);
  }
}

export async function renderClaimAccount() {
  const form = byId<HTMLFormElement>("claim-account-form");
  const result = byId("claim-account-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = (byId("claim-username") as HTMLInputElement).value.trim();
    if (!username) { result.innerHTML = status("Username is required."); return; }
    try {
      const res = await api.claimAccount({ username });
      result.innerHTML = status(res.message || "Claim submitted for admin review.");
    } catch (err: any) {
      result.innerHTML = status(`Error: ${err.message}`);
    }
  });
}

export async function renderAccount() {
  const [profile, phoneProviders, themes] = await Promise.all([
    dataProvider.getProfile(),
    api.getPhoneProviders(),
    api.getThemes(),
  ]);
  const claims = decodeClaims(profile.claims);
  const isDefunct = profile.status === "defunct";

  // Show defunct banner if account is read-only
  const bannerArea = document.getElementById("defunct-banner-area");
  if (isDefunct && bannerArea) {
    bannerArea.innerHTML = `<div class="defunct-banner">Your account is disabled (read-only). Contact an admin to re-activate.</div>`;
  }

  const currentProvider = profile.phone_provider ?? "";
  const providerOptions = phoneProviders
    .map(p => `<option value="${p}" ${p === currentProvider ? "selected" : ""}>${p.replace(/_/g, " ")}</option>`)
    .join("");
  const oidcEmail = profile.oidc_email ?? profile.email ?? "";
  const emailStored = profile.email !== null && profile.email !== "";
  byId("profile-form").innerHTML = `
    <label>Username</label>
    <input id="username-input" value="${esc(profile.username)}" maxlength="36" />
    <label>Email</label>
    <input value="${esc(oidcEmail)}" disabled style="background: #2a2a2a; color: #888;" />
    <p style="font-size: 0.85em; color: #aaa; margin: 4px 0 12px 0;">Tied to your login provider — cannot be changed here.</p>
    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer; margin-bottom: 12px;">
      <input type="checkbox" id="email-notify-toggle" ${emailStored ? "checked" : ""} />
      <span>Save email for notifications</span>
    </label>
    <label>Phone</label>
    <input id="phone-input" value="${esc(profile.phone ?? "")}" placeholder="555-123-4567" />
    <label>Carrier</label>
    <select id="provider-select"><option value="">-- none --</option>${providerOptions}</select>
    <button type="button" id="save-profile-btn" style="margin-top: 12px;" ${isDefunct ? "disabled" : ""}>Save Profile</button>
  `;
  
  byId("save-profile-btn")?.addEventListener("click", async () => {
    const newUsername = (byId("username-input") as HTMLInputElement).value.trim();
    const saveEmail = (byId("email-notify-toggle") as HTMLInputElement).checked;
    const rawPhone = (byId("phone-input") as HTMLInputElement).value.trim();
    const phone = rawPhone.replace(/[\s().+-]/g, "");  // strip formatting chars
    const phone_provider = (byId("provider-select") as HTMLSelectElement).value.trim();
    const emailPatch: { email: string } = { email: saveEmail ? oidcEmail : "" };
    const update: Record<string, any> = {
      ...emailPatch,
      phone: phone || undefined,
      phone_provider: phone_provider || undefined,
    };
    // Only send username if it changed
    if (newUsername && newUsername !== profile.username) {
      update.username = newUsername;
    }
    try {
      const updated = await api.updateProfile(update);
      profile.username = updated.username;  // keep local state in sync
      byId("account-result").innerHTML = status("Profile saved.");
    } catch (err: any) {
      byId("account-result").innerHTML = status(`Error: ${err.message}`);
    }
  });
  
  const claimsContainer = byId("claims-form");
  
  const claimLabels: Record<string, string> = {
    "MEALBOT": "Mealbot",
    "HAPPY_HOUR": "Happy Hour",
    "HAPPY_HOUR_TYRANT": "Happy Hour Management"
  };
  
  const editableClaims = ["MEALBOT", "HAPPY_HOUR", "HAPPY_HOUR_TYRANT"];
  
  claimsContainer.innerHTML = editableClaims
    .map((claim) => {
      const label = claimLabels[claim] || claim;
      const checked = claims.includes(claim) ? "checked" : "";
      const disabled = isDefunct ? "disabled" : "";
      return `<label style="display: flex; align-items: center; margin: 12px 0; padding: 8px; cursor: pointer;"><input type="checkbox" class="claim-checkbox" data-claim="${claim}" ${checked} ${disabled} style="margin-right: 10px;" /><span>${label}</span></label>`;
    })
    .join("");
  
  claimsContainer.querySelectorAll(".claim-checkbox").forEach((checkbox) => {
    checkbox.addEventListener("change", async () => {
      const input = checkbox as HTMLInputElement;
      const claim = input.dataset.claim!;
      try {
        if (input.checked) {
          await api.updateClaims({ add: [claim] });
        } else {
          await api.updateClaims({ remove: [claim] });
        }
        byId("account-result").innerHTML = status("Feature access updated.");
      } catch (err: any) {
        input.checked = !input.checked; // revert on failure
        byId("account-result").innerHTML = status(`Error: ${err.message}`);
      }
    });
  });

  // ── Theme Picker ──────────────────────────────────────────────────
  const themePicker = document.getElementById("theme-picker");
  if (themePicker) {
    const themeLabels: Record<string, string> = {
      "default": "Default Dark",
      "arachne": "Bauhaus Studio",
      "daedalus": "Blueprint",
      "aphrodite": "Washi",
      "niflheim": "Frosted Glass",
      "norns": "Gothic Cathedral",
      "quetzalcoatl": "Hacker Terminal",
      "atlas": "Neon Dystopia",
      "thoth": "Deep Sea",
      "yggdrasil": "Enchanted Wood",
      "amaterasu": "Desert Mirage",
      "hecate": "Cosmic Nebula",
      "freya": "Sakura Garden",
      "hermes": "Mainframe CRT",
      "prometheus": "Brutalist A11y",
      "gaia": "Artisan Pottery",
      "skadi": "Scandinavian",
      "raijin": "8-Bit Arcade",
      "seshat": "Broadsheet",
      "hephaestus": "Command Center",
      "vishnu": "Art Deco",
      "cernunnos": "Jewel Box",
      "brigid": "Cozy Cafe",
    };
    const currentTheme = profile.theme || "default";
    themePicker.innerHTML = `<div class="theme-picker">${
      themes.map((t) => {
        const label = themeLabels[t] || t;
        const active = t === currentTheme ? "active" : "";
        return `<div class="theme-swatch ${active}" data-theme-name="${esc(t)}">${esc(label)}</div>`;
      }).join("")
    }</div>`;

    themePicker.querySelectorAll(".theme-swatch").forEach((swatch) => {
      swatch.addEventListener("click", async () => {
        const themeName = (swatch as HTMLElement).dataset.themeName!;
        // Apply immediately for instant feedback
        if (themeName === "default") {
          document.documentElement.removeAttribute("data-theme");
          localStorage.removeItem("vibe-theme");
        } else {
          document.documentElement.setAttribute("data-theme", themeName);
          localStorage.setItem("vibe-theme", themeName);
        }
        // Update active state
        themePicker.querySelectorAll(".theme-swatch").forEach(s => s.classList.remove("active"));
        swatch.classList.add("active");
        // Persist to server
        try {
          await api.setTheme(themeName);
        } catch (err: any) {
          byId("account-result").innerHTML = status(`Error saving theme: ${err.message}`);
        }
      });
    });
  }
}

export async function renderMealbot() {
  const BATCH_SIZE = 20;

  const [individualizedData, ledgerPage, myLedgerPage, allUsers, profile] = await Promise.all([
    dataProvider.getIndividualizedSummary(),
    api.getMealbotLedgerPage(1, BATCH_SIZE),
    api.getMyMealbotLedgerPage(1, BATCH_SIZE),
    dataProvider.getAllUsers(),
    dataProvider.getProfile(),
  ]);
  const currentUser = profile.username;
  const otherUsers = allUsers.filter(u => u !== currentUser);

  // ── Helpers to (re-)render data sections ──────────────────────────
  function renderDebtCards(data: typeof individualizedData) {
    byId("incoming-debts").innerHTML = data.incoming.length > 0 ? table(
      ["User", "Meals"],
      data.incoming.map((item) => [item.from, `${item.credits}`]),
    ) : "<p>All square!</p>";

    byId("outgoing-debts").innerHTML = data.outgoing.length > 0 ? table(
      ["User", "Meals"],
      data.outgoing.map((item) => [item.to, `${item.credits}`]),
    ) : "<p>All square!</p>";
  }

  function renderLedger(containerId: string, page: typeof ledgerPage) {
    const rows = page.items.map((row) => {
      const isInvolved = row.payer === currentUser || row.recipient === currentUser;
      const voidBtn = isInvolved
        ? `<button type="button" class="void-record-btn" data-record-id="${row.id}" style="font-size: 0.8em; padding: 2px 8px;">Void</button>`
        : "";
      return [row.payer, row.recipient, formatDate(row.date), voidBtn];
    });
    byId(containerId).innerHTML = table(
      ["Payer", "Recipient", "Date", ""],
      rows,
      { rawColumns: [3] },
    );

    // Wire up void buttons
    byId(containerId).querySelectorAll(".void-record-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const recordId = Number((btn as HTMLElement).dataset.recordId);
        if (!confirm("Void this record? This cannot be undone.")) return;
        try {
          await api.voidMealbotRecord(recordId);
          byId("mealbot-record-result").innerHTML = status("Record voided.");
          await refreshAfterRecord();
        } catch (err: any) {
          byId("mealbot-record-result").innerHTML = status(`Error: ${err.message}`);
        }
      });
    });
  }

  async function refreshAfterRecord() {
    const [newData, newLedger, newMyLedger] = await Promise.all([
      dataProvider.getIndividualizedSummary(),
      api.getMealbotLedgerPage(1, BATCH_SIZE),
      api.getMyMealbotLedgerPage(1, BATCH_SIZE),
    ]);
    renderDebtCards(newData);
    renderLedger("mealbot-ledger", newLedger);
    renderLedger("mealbot-my-ledger", newMyLedger);
  }

  renderDebtCards(individualizedData);

  byId("mealbot-record-form").innerHTML = `
    <label>Other person</label>
    <input list="other-user-list" id="other-user-input" value="${esc(otherUsers[0] || '')}" />
    <datalist id="other-user-list">${otherUsers.map((u) => `<option value="${esc(u)}">`).join("")}</datalist>
    
    <div style="margin: 12px 0;">
      <button type="button" id="i-paid-btn" style="margin-right: 8px;">I Paid</button>
      <button type="button" id="they-paid-btn">They Paid</button>
    </div>
  `;
  
  byId("i-paid-btn")?.addEventListener("click", async () => {
    const other = (byId("other-user-input") as HTMLInputElement).value.trim();
    if (!other) { byId("mealbot-record-result").innerHTML = status("Select a person."); return; }
    try {
      await api.createMealbotRecord({ payer: currentUser, recipient: other, credits: 1 });
      byId("mealbot-record-result").innerHTML = status(`Recorded: ${currentUser} paid for ${other}`);
      await refreshAfterRecord();
    } catch (err: any) {
      byId("mealbot-record-result").innerHTML = status(`Error: ${err.message}`);
    }
  });
  
  byId("they-paid-btn")?.addEventListener("click", async () => {
    const other = (byId("other-user-input") as HTMLInputElement).value.trim();
    if (!other) { byId("mealbot-record-result").innerHTML = status("Select a person."); return; }
    try {
      await api.createMealbotRecord({ payer: other, recipient: currentUser, credits: 1 });
      byId("mealbot-record-result").innerHTML = status(`Recorded: ${other} paid for ${currentUser}`);
      await refreshAfterRecord();
    } catch (err: any) {
      byId("mealbot-record-result").innerHTML = status(`Error: ${err.message}`);
    }
  });

  // Render initial page of ledger (server-paginated)
  renderLedger("mealbot-ledger", ledgerPage);

  setupServerPaginatedScroll({
    scrollContainerId: "ledger-scroll-container",
    sentinelId: "ledger-sentinel",
    statusId: "ledger-status",
    pageSize: BATCH_SIZE,
    totalItems: ledgerPage.total,
    fetchPage: async (page) => {
      const resp = await api.getMealbotLedgerPage(page, BATCH_SIZE);
      return resp.items.map((row) => [row.payer, row.recipient, formatDate(row.date)]);
    },
  });

  // Render initial page of my ledger (server-paginated)
  renderLedger("mealbot-my-ledger", myLedgerPage);

  setupServerPaginatedScroll({
    scrollContainerId: "my-ledger-scroll-container",
    sentinelId: "my-ledger-sentinel",
    statusId: "my-ledger-status",
    pageSize: BATCH_SIZE,
    totalItems: myLedgerPage.total,
    fetchPage: async (page) => {
      const resp = await api.getMyMealbotLedgerPage(page, BATCH_SIZE);
      return resp.items.map((row) => [row.payer, row.recipient, formatDate(row.date)]);
    },
  });
}

export async function renderHappyHour() {
  const BATCH_SIZE = 20;
  let profile: { username: string; claims: number } | null = null;
  try {
    profile = await api.getProfile();
  } catch { /* not authenticated */ }

  const hasTyrant = profile !== null && (profile.claims & 32) !== 0; // HAPPY_HOUR_TYRANT = 32

  try {
    const fetches: [
      Promise<any>, Promise<any>, Promise<any>,
      Promise<any>, Promise<any>,
    ] = [
      dataProvider.getUpcomingHappyHour(),
      api.getEventsPage(1, BATCH_SIZE),
      dataProvider.getRotation(),
      hasTyrant ? dataProvider.getLocations() : Promise.resolve([]),
      hasTyrant ? dataProvider.isCurrentUserTurn() : Promise.resolve(false),
    ];
    const [upcoming, eventsPage, rotation, locations, isTurn] = await Promise.all(fetches);

    // ── Helper: render upcoming event card ──
    function renderUpcoming(u: any) {
      const nameHtml = u.location_url
        ? `<a href="${esc(u.location_url)}" target="_blank" rel="noopener">${esc(u.location_name || "TBD")}</a>`
        : esc(u.location_name || "TBD");
      const addressHtml = u.location_address
        ? `<br><span style="color:#aaa; font-size: 0.9em;">${esc(u.location_address)}</span>`
        : "";
      const isRealEvent = u.id && u.id > 0;
      const recoveryButtons = hasTyrant && isRealEvent
        ? `<td>
            <button type="button" class="cancel-event-btn" data-event-id="${u.id}" style="margin-right: 6px;">Cancel</button>
          </td>`
        : "";
      const recoveryHeader = hasTyrant && isRealEvent ? "<th></th>" : "";
      byId("happyhour-upcoming").innerHTML = `
        <table><thead><tr><th>When</th><th>Location</th><th>Chosen By</th>${recoveryHeader}</tr></thead>
        <tbody><tr>
          <td>${u.when ? formatDate(u.when) : "TBD"}</td>
          <td>${nameHtml}${addressHtml}</td>
          <td>${esc(u.tyrant_username ?? "TBD")}</td>
          ${recoveryButtons}
        </tr></tbody></table>`;

      // Wire up cancel button
      if (hasTyrant && isRealEvent) {
        const cancelBtn = document.querySelector(".cancel-event-btn") as HTMLElement | null;
        if (cancelBtn) {
          cancelBtn.addEventListener("click", async () => {
            if (!confirm("Are you sure you want to cancel this happy hour? This will notify everyone.")) return;
            try {
              await api.cancelEvent(u.id);
              byId("happyhour-result").innerHTML = status("Happy hour cancelled. You can now submit a new one for this week.");
              // Refresh all data
              const [newUpcoming, newRotation, newEvents] = await Promise.all([
                dataProvider.getUpcomingHappyHour(),
                dataProvider.getRotation(),
                api.getEventsPage(1, BATCH_SIZE),
              ]);
              renderUpcoming(newUpcoming);
              byId("happyhour-rotation").innerHTML = newRotation.length > 0
                ? table(["User", "Week"], newRotation.map((item: any) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]))
                : "<p style='color:#aaa;'>No rotation yet.</p>";
              renderEventsTable(newEvents);
            } catch (err: any) {
              byId("happyhour-result").innerHTML = status(`Error: ${err.message}`);
            }
          });
        }
      }
    }

    renderUpcoming(upcoming);

    // ── Rotation ──
    byId("happyhour-rotation").innerHTML = rotation.length > 0
      ? table(["User", "Week"], rotation.map((item: any) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]))
      : "<p style='color:#aaa;'>No rotation yet — submit a happy hour choice to get started.</p>";

    // ── Helper: render events table ──
    function renderEventsTable(page: any) {
      byId("happyhour-events").innerHTML = table(
        ["When", "Location", "Chosen By"],
        page.items.map((item: any) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]),
      );
    }

    // ── Past events (server-paginated) ──
    renderEventsTable(eventsPage);
    setupServerPaginatedScroll({
      scrollContainerId: "events-scroll-container",
      sentinelId: "events-sentinel",
      statusId: "events-status",
      pageSize: BATCH_SIZE,
      totalItems: eventsPage.total,
      fetchPage: async (page) => {
        const resp = await api.getEventsPage(page, BATCH_SIZE);
        return resp.items.map((item: any) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]);
      },
    });

    // ── Management sections (HAPPY_HOUR_TYRANT only) ──
    if (hasTyrant) {
      // Show the submit and locations sections
      const submitSection = document.getElementById("happyhour-submit-section");
      if (submitSection) submitSection.style.display = "";
      const locationsSection = document.getElementById("happyhour-locations-section");
      if (locationsSection) locationsSection.style.display = "";

      // Turn status
      if (isTurn) {
        byId("happyhour-turn-status").innerHTML = status("It is your turn to pick the next happy hour location.") +
          `<button type="button" id="skip-turn-btn" style="margin-top: 8px;">Skip My Turn</button>`;
      } else {
        byId("happyhour-turn-status").innerHTML = status("It is not your turn, but you can still submit early if you'd like.");
      }

      // Wire up skip turn button
      document.getElementById("skip-turn-btn")?.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to skip your turn? The next person in rotation will be activated.")) return;
        try {
          const result = await api.skipRotationTurn();
          const nextMsg = result.next_user ? ` ${result.next_user} is now up.` : "";
          byId("happyhour-result").innerHTML = status(`Turn skipped.${nextMsg}`);
          // Refresh rotation and upcoming
          const [newUpcoming, newRotation] = await Promise.all([
            dataProvider.getUpcomingHappyHour(),
            dataProvider.getRotation(),
          ]);
          renderUpcoming(newUpcoming);
          byId("happyhour-rotation").innerHTML = newRotation.length > 0
            ? table(["User", "Week"], newRotation.map((item: any) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]))
            : "<p style='color:#aaa;'>No rotation yet.</p>";
          byId("happyhour-turn-status").innerHTML = status("You have skipped your turn.");
        } catch (err: any) {
          byId("happyhour-result").innerHTML = status(`Error: ${err.message}`);
        }
      });

      // Always render the form for tyrants (backend enforces rotation rules)
      const nextFriday = (() => {
        const now = new Date();
        const day = now.getUTCDay();
        const daysUntilFriday = (5 - day + 7) % 7 || 7;
        const fri = new Date(now);
        fri.setUTCDate(fri.getUTCDate() + daysUntilFriday);
        const testDate = new Date(fri.toISOString().split("T")[0] + "T12:00:00-08:00");
        const pacificHour = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", hour12: false }).format(testDate);
        const isPDT = parseInt(pacificHour) === 13;
        const utcHour = isPDT ? 23 : 24;
        fri.setUTCHours(utcHour % 24, 0, 0, 0);
        if (utcHour === 24) fri.setUTCDate(fri.getUTCDate() + 1);
        return fri.toISOString();
      })();

      byId("happyhour-create-form").innerHTML = `
        <p style="font-size: 0.9em; color: #aaa; margin-bottom: 12px;">Happy hour is always scheduled for Friday at 4:00 PM Pacific.</p>
        <label>Location</label>
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px;">
          <select id="location-select" style="flex: 1;">
            ${locations.filter((l: any) => !l.closed).map((l: any) => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}
            <option value="new">➕ Add New Location...</option>
          </select>
          <button type="button" id="weighted-random-btn" title="Favors less-visited locations">🎲 Random</button>
          <button type="button" id="true-random-btn" title="Equal chance for all locations">🎯 True Random</button>
        </div>
        <div id="new-location-fields" style="display: none; margin-top: 12px; padding: 12px; border: 1px solid #444; border-radius: 6px;">
          <label>Location Name</label><input id="new-location-name" placeholder="New Venue" />
          <label>URL (optional)</label><input id="new-location-url" placeholder="https://example.com" />
          <label>Address</label><textarea id="new-location-address" rows="2" placeholder="123 Main St, Austin, TX 78701"></textarea>
        </div>
        <label>Description (optional)</label>
        <input id="event-description" placeholder="Weekly happy hour" />
        <button type="button" id="submit-happyhour-btn" style="margin-top: 12px;">Submit Happy Hour</button>
      `;

      const locationSelect = byId("location-select") as HTMLSelectElement;
      const newLocationFields = byId("new-location-fields");

      // Show new-location fields if "new" is already selected (e.g. no existing locations)
      if (locationSelect.value === "new") {
        newLocationFields.style.display = "block";
      }

      locationSelect.addEventListener("change", () => {
        newLocationFields.style.display = locationSelect.value === "new" ? "block" : "none";
      });

      byId("weighted-random-btn")?.addEventListener("click", async () => {
        try {
          const loc = await api.getRandomLocation(true);
          locationSelect.value = String(loc.id);
          newLocationFields.style.display = "none";
        } catch {
          // Fallback to client-side if the endpoint fails
          const openLocations = locations.filter((l: any) => !l.closed);
          if (openLocations.length > 0) {
            const randomLocation = openLocations[Math.floor(Math.random() * openLocations.length)];
            locationSelect.value = String(randomLocation.id);
            newLocationFields.style.display = "none";
          }
        }
      });

      byId("true-random-btn")?.addEventListener("click", async () => {
        try {
          const loc = await api.getRandomLocation(false);
          locationSelect.value = String(loc.id);
          newLocationFields.style.display = "none";
        } catch {
          // Fallback to client-side if the endpoint fails
          const openLocations = locations.filter((l: any) => !l.closed);
          if (openLocations.length > 0) {
            const randomLocation = openLocations[Math.floor(Math.random() * openLocations.length)];
            locationSelect.value = String(randomLocation.id);
            newLocationFields.style.display = "none";
          }
        }
      });

      byId("submit-happyhour-btn")?.addEventListener("click", async () => {
        const description = (byId("event-description") as HTMLInputElement).value.trim() || undefined;
        try {
          let locationId: number;
          if (locationSelect.value === "new") {
            const name = (byId("new-location-name") as HTMLInputElement).value.trim();
            const url = (byId("new-location-url") as HTMLInputElement).value.trim() || undefined;
            const address = (byId("new-location-address") as HTMLTextAreaElement).value.trim();
            if (!name || !address) {
              byId("happyhour-result").innerHTML = status("Name and address are required for new locations.");
              return;
            }
            const newLoc = await api.createLocation({
              name, url, address_raw: address,
              ...parseAddress(address),
            });
            locationId = newLoc.id;
          } else {
            locationId = Number(locationSelect.value);
          }
          const event = await api.createEvent({ location_id: locationId, description, when: nextFriday });
          byId("happyhour-result").innerHTML = status(`Happy hour scheduled at ${event.location_name} for ${formatDate(event.when)}`);
          // Refresh all data sections
          const [newUpcoming, newRotation, newEvents, newLocations] = await Promise.all([
            dataProvider.getUpcomingHappyHour(),
            dataProvider.getRotation(),
            api.getEventsPage(1, BATCH_SIZE),
            dataProvider.getLocations(),
          ]);
          renderUpcoming(newUpcoming);
          byId("happyhour-rotation").innerHTML = newRotation.length > 0
            ? table(["User", "Week"], newRotation.map((item: any) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]))
            : "<p style='color:#aaa;'>No rotation yet.</p>";
          renderEventsTable(newEvents);
          renderLocationsTable(newLocations);
        } catch (err: any) {
          const msg = err.message || String(err);
          if (msg.toLowerCase().includes("already exists") || msg.toLowerCase().includes("already")) {
            byId("happyhour-result").innerHTML = status("A happy hour event has already been submitted for this week.");
          } else {
            byId("happyhour-result").innerHTML = status(`Error: ${msg}`);
          }
        }
      });

      // ── Helper: render locations table ──
      function renderLocationsTable(locs: any[]) {
        byId("happyhour-locations").innerHTML = table(
          ["Name", "Address"],
          locs.map((item: any) => {
            const nameHtml = item.url
              ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.name)}</a>`
              : esc(item.name);
            return [nameHtml, item.address_raw || `${item.city}, ${item.state}`];
          }),
          { rawColumns: [0] },
        );
      }

      // ── Locations ──
      renderLocationsTable(locations);
    }
  } catch {
    // Unauthenticated or missing claims — show login prompt
    const loginLink = esc(api.loginUrl("google", "/happyhour"));
    byId("happyhour-upcoming").innerHTML = status(
      `<a href="${loginLink}">Log in with a Happy Hour account</a> to view live happy hour data.`,
      { safe: true },
    );
    const rotEl = document.getElementById("happyhour-rotation");
    if (rotEl) rotEl.innerHTML = "";
    const evtEl = document.getElementById("happyhour-events");
    if (evtEl) evtEl.innerHTML = "";
  }
}

export async function renderAdmin() {
  // ── Tab switching ─────────────────────────────────────────────────
  const tabs = document.querySelectorAll<HTMLElement>(".admin-tab");
  const panels = document.querySelectorAll<HTMLElement>(".admin-panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab!;
      panels.forEach((p) => {
        p.style.display = p.id === `admin-tab-${target}` ? "" : "none";
      });
    });
  });

  // ── Pending Accounts ──────────────────────────────────────────────
  const pendingList = document.getElementById("admin-pending-list")!;
  const pendingResult = document.getElementById("admin-pending-result")!;

  async function loadPending() {
    try {
      const accounts = await api.getAdminAccounts("pending_approval");
      if (accounts.length === 0) {
        pendingList.innerHTML = "<p>No pending accounts.</p>";
        return;
      }
      pendingList.innerHTML = accounts.map((a) => `
        <div class="card" style="margin-bottom: 12px; padding: 16px;">
          <p><strong>Username:</strong> ${esc(a.username)}</p>
          <p><strong>Email:</strong> ${esc(a.email ?? "none")}</p>
          <p><strong>Provider:</strong> ${esc(a.provider)}</p>
          <p><strong>Status:</strong> ${esc(a.status)}</p>
          <div style="margin-top: 8px;">
            <button type="button" class="approve-account-btn" data-id="${a.id}" style="margin-right: 8px;">Approve</button>
            <button type="button" class="deny-account-btn" data-id="${a.id}">Deny (Ban)</button>
          </div>
        </div>
      `).join("");

      pendingList.querySelectorAll(".approve-account-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.id);
          try {
            await api.updateAccountStatus(id, { status: "active" });
            pendingResult.innerHTML = status("Account approved.");
            await loadPending();
          } catch (err: any) { pendingResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });
      pendingList.querySelectorAll(".deny-account-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.id);
          try {
            await api.updateAccountStatus(id, { status: "banned" });
            pendingResult.innerHTML = status("Account denied (banned).");
            await loadPending();
          } catch (err: any) { pendingResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });
    } catch (err: any) {
      pendingList.innerHTML = status(`Error loading pending accounts: ${err.message}`);
    }
  }

  // ── All Accounts ──────────────────────────────────────────────────
  const accountsList = document.getElementById("admin-accounts-list")!;
  const accountsResult = document.getElementById("admin-accounts-result")!;
  const statusFilter = document.getElementById("admin-status-filter") as HTMLSelectElement;

  async function loadAccounts(filter?: string) {
    try {
      const accounts = await api.getAdminAccounts(filter || undefined);
      if (accounts.length === 0) {
        accountsList.innerHTML = "<p>No accounts found.</p>";
        return;
      }
      accountsList.innerHTML = accounts.map((a) => `
        <div class="card" style="margin-bottom: 12px; padding: 16px;">
          <p><strong>ID:</strong> ${a.id} &nbsp; <strong>Username:</strong> ${esc(a.username)}</p>
          <p><strong>Email:</strong> ${esc(a.email ?? "none")} &nbsp; <strong>Provider:</strong> ${esc(a.provider)}</p>
          <p><strong>Status:</strong> <span class="account-status-${a.id}">${esc(a.status)}</span>
             &nbsp; <strong>Claims:</strong> ${a.claims}</p>
          <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap;">
            ${a.status !== "active" ? `<button type="button" class="set-status-btn" data-id="${a.id}" data-status="active">Activate</button>` : ""}
            ${a.status !== "banned" ? `<button type="button" class="set-status-btn" data-id="${a.id}" data-status="banned">Ban</button>` : ""}
            ${a.status !== "defunct" ? `<button type="button" class="set-status-btn" data-id="${a.id}" data-status="defunct">Defunct</button>` : ""}
            <button type="button" class="toggle-admin-btn" data-id="${a.id}" data-has-admin="${(a.claims & 2) !== 0}">
              ${(a.claims & 2) !== 0 ? "Revoke Admin" : "Grant Admin"}
            </button>
          </div>
        </div>
      `).join("");

      accountsList.querySelectorAll(".set-status-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const el = btn as HTMLElement;
          const id = Number(el.dataset.id);
          const newStatus = el.dataset.status!;
          try {
            await api.updateAccountStatus(id, { status: newStatus });
            accountsResult.innerHTML = status(`Account ${id} set to ${newStatus}.`);
            await loadAccounts(statusFilter.value);
          } catch (err: any) { accountsResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });

      accountsList.querySelectorAll(".toggle-admin-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const el = btn as HTMLElement;
          const id = Number(el.dataset.id);
          const hasAdmin = el.dataset.hasAdmin === "true";
          try {
            await api.updateAccountRole(id, { grant_admin: !hasAdmin });
            accountsResult.innerHTML = status(`Admin role ${hasAdmin ? "revoked" : "granted"} for account ${id}.`);
            await loadAccounts(statusFilter.value);
          } catch (err: any) { accountsResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });
    } catch (err: any) {
      accountsList.innerHTML = status(`Error loading accounts: ${err.message}`);
    }
  }

  statusFilter.addEventListener("change", () => loadAccounts(statusFilter.value));

  // ── Claim Requests ────────────────────────────────────────────────
  const claimsContainer = document.getElementById("admin-claims-list")!;
  const claimsResult = document.getElementById("admin-claims-result")!;

  async function loadClaims() {
    try {
      const claims = await api.getClaimRequests();
      if (claims.length === 0) {
        claimsContainer.innerHTML = "<p>No pending claim requests.</p>";
        return;
      }
      claimsContainer.innerHTML = claims.map((c) => `
        <div class="card" style="margin-bottom: 12px; padding: 16px;">
          <p><strong>Requester:</strong> ${esc(c.requester_name)} (${esc(c.requester_email ?? "no email")})</p>
          <p><strong>Provider:</strong> ${esc(c.requester_provider)}</p>
          <p><strong>Target account:</strong> ${esc(c.target_username)} (#${c.target_account_id})</p>
          <p><strong>Status:</strong> ${esc(c.status)}</p>
          <p><strong>Submitted:</strong> ${c.created_at ? formatDate(c.created_at) : "unknown"}</p>
          ${c.status === "pending" ? `
            <div style="margin-top: 8px;">
              <button type="button" class="approve-claim-btn" data-claim-id="${c.id}" style="margin-right: 8px;">Approve</button>
              <button type="button" class="deny-claim-btn" data-claim-id="${c.id}">Deny</button>
            </div>
          ` : `<p><strong>Resolved:</strong> ${c.resolved_at ? formatDate(c.resolved_at) : ""}</p>`}
        </div>
      `).join("");

      claimsContainer.querySelectorAll(".approve-claim-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.claimId);
          try {
            await api.reviewClaimRequest(id, { decision: "approve" });
            claimsResult.innerHTML = status("Claim approved.");
            await loadClaims();
          } catch (err: any) { claimsResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });

      claimsContainer.querySelectorAll(".deny-claim-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.claimId);
          try {
            await api.reviewClaimRequest(id, { decision: "deny" });
            claimsResult.innerHTML = status("Claim denied.");
            await loadClaims();
          } catch (err: any) { claimsResult.innerHTML = status(`Error: ${err.message}`); }
        });
      });
    } catch (err: any) {
      claimsContainer.innerHTML = status(`Error loading claims: ${err.message}`);
    }
  }

  // Load all tabs on page load
  await Promise.all([loadPending(), loadAccounts(), loadClaims()]);
}
