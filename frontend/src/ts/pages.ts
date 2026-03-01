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
  let html = `
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
      result.innerHTML = status(`Registration complete! Welcome, ${res.username}.`);
      setTimeout(() => { window.location.href = "/account"; }, 1500);
    } catch (err: any) {
      result.innerHTML = status(`Error: ${err.message}`);
    }
  });
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
  const profile = await dataProvider.getProfile();
  const claims = decodeClaims(profile.claims);
  
  byId("profile-form").innerHTML = `
    <label>Username</label>
    <input value="${esc(profile.username)}" disabled />
    <label>Email</label>
    <input value="${esc(profile.email ?? "")}" disabled style="background: #2a2a2a; color: #888;" />
    <p style="font-size: 0.85em; color: #aaa; margin: 4px 0 12px 0;">Tied to OIDC login</p>
    <label>Phone</label>
    <input id="phone-input" value="${esc(profile.phone ?? "")}" placeholder="5551234567" />
    <label>Provider</label>
    <input id="provider-input" value="${esc(profile.phone_provider ?? "")}" placeholder="verizon" />
    <button type="button" id="save-profile-btn" style="margin-top: 12px;">Save Profile</button>
  `;
  
  byId("save-profile-btn")?.addEventListener("click", async () => {
    const phone = (byId("phone-input") as HTMLInputElement).value.trim();
    const phone_provider = (byId("provider-input") as HTMLInputElement).value.trim();
    try {
      await api.updateProfile({ phone: phone || undefined, phone_provider: phone_provider || undefined });
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
      return `<label style="display: flex; align-items: center; margin: 12px 0; padding: 8px; cursor: pointer;"><input type="checkbox" class="claim-checkbox" data-claim="${claim}" ${checked} style="margin-right: 10px;" /><span>${label}</span></label>`;
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
}

export async function renderMealbot() {
  const BATCH_SIZE = 20;

  const [summary, ledgerPage, myLedgerPage, allUsers, profile] = await Promise.all([
    dataProvider.getMealbotSummary(),
    api.getMealbotLedgerPage(1, BATCH_SIZE),
    api.getMyMealbotLedgerPage(1, BATCH_SIZE),
    dataProvider.getAllUsers(),
    dataProvider.getProfile(),
  ]);
  const currentUser = profile.username;
  const otherUsers = allUsers.filter(u => u !== currentUser);

  byId("mealbot-summary").innerHTML = table(
    ["User", "Balance"],
    summary.balances.map((entry) => {
      const balance = entry.net > 0 ? `Owes you ${entry.net}` : entry.net < 0 ? `You owe ${-entry.net}` : "Even";
      return [entry.user, balance];
    }),
  );

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
    } catch (err: any) {
      byId("mealbot-record-result").innerHTML = status(`Error: ${err.message}`);
    }
  });

  // Render initial page of ledger (server-paginated)
  byId("mealbot-ledger").innerHTML = table(
    ["Payer", "Recipient", "Date"],
    ledgerPage.items.map((row) => [row.payer, row.recipient, formatDate(row.date)]),
  );

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
  byId("mealbot-my-ledger").innerHTML = table(
    ["Payer", "Recipient", "Date"],
    myLedgerPage.items.map((row) => [row.payer, row.recipient, formatDate(row.date)]),
  );

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

export async function renderMealbotIndividualized() {
  const BATCH_SIZE = 20;

  const [data, myLedgerPage] = await Promise.all([
    dataProvider.getIndividualizedSummary(),
    api.getMyMealbotLedgerPage(1, BATCH_SIZE),
  ]);

  byId("incoming-debts").innerHTML = data.incoming.length > 0 ? table(
    ["User", "Amount"],
    data.incoming.map((item) => [item.from, `Owes you ${item.credits} meal${item.credits !== 1 ? 's' : ''}`]),
  ) : "<p>No incoming debts</p>";
  
  byId("outgoing-debts").innerHTML = data.outgoing.length > 0 ? table(
    ["User", "Amount"],
    data.outgoing.map((item) => [item.to, `You owe ${item.credits} meal${item.credits !== 1 ? 's' : ''}`]),
  ) : "<p>No outgoing debts</p>";
  
  // Render initial page (server-paginated)
  byId("my-recent-ledger").innerHTML = table(
    ["Payer", "Recipient", "Date"],
    myLedgerPage.items.map((item) => [item.payer, item.recipient, formatDate(item.date)]),
  );
  
  setupServerPaginatedScroll({
    scrollContainerId: "recent-ledger-scroll-container",
    sentinelId: "recent-ledger-sentinel",
    statusId: "recent-ledger-status",
    pageSize: BATCH_SIZE,
    totalItems: myLedgerPage.total,
    fetchPage: async (page) => {
      const resp = await api.getMyMealbotLedgerPage(page, BATCH_SIZE);
      return resp.items.map((item) => [item.payer, item.recipient, formatDate(item.date)]);
    },
  });
}

export async function renderPublicHappyHour() {
  try {
    const BATCH_SIZE = 20;

    const [upcoming, eventsPage, rotation] = await Promise.all([
      dataProvider.getUpcomingHappyHour(),
      api.getEventsPage(1, BATCH_SIZE),
      dataProvider.getRotation(),
    ]);

    byId("public-current-happyhour").innerHTML = table(
      ["When", "Location", "Chosen By"],
      [[upcoming.when ? formatDate(upcoming.when) : "TBD", upcoming.location_name || "TBD", upcoming.tyrant_username ?? "TBD"]],
    );

    byId("public-rotation").innerHTML = table(
      ["User", "Week"],
      rotation.map((item) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]),
    );

    // Render initial page of past events (server-paginated)
    byId("public-past-happyhours").innerHTML = table(
      ["When", "Location", "Chosen By"],
      eventsPage.items.map((item) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]),
    );

    setupServerPaginatedScroll({
      scrollContainerId: "past-scroll-container",
      sentinelId: "past-sentinel",
      statusId: "past-status",
      pageSize: BATCH_SIZE,
      totalItems: eventsPage.total,
      fetchPage: async (page) => {
        const resp = await api.getEventsPage(page, BATCH_SIZE);
        return resp.items.map((item) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]);
      },
    });
  } catch {
    // Unauthenticated or missing claims – show login prompt
    const loginLink = esc(api.loginUrl("google", "/happyhour"));
    byId("public-current-happyhour").innerHTML = status(
      `<a href="${loginLink}">Log in with a Happy Hour account</a> to view live happy hour data.`,
      { safe: true },
    );
    const rotEl = document.getElementById("public-rotation");
    if (rotEl) rotEl.innerHTML = "";
    const pastEl = document.getElementById("public-past-happyhours");
    if (pastEl) pastEl.innerHTML = "";
  }
}

export async function renderHappyHourManage() {
  const BATCH_SIZE = 20;

  const [upcoming, rotation, locations, eventsPage, isTurn] = await Promise.all([
    dataProvider.getUpcomingHappyHour(),
    dataProvider.getRotation(),
    dataProvider.getLocations(),
    api.getEventsPage(1, BATCH_SIZE),
    dataProvider.isCurrentUserTurn(),
  ]);

  byId("upcoming-event").innerHTML = table(
    ["When", "Location", "Chosen By"],
    [[formatDate(upcoming.when), upcoming.location_name, upcoming.tyrant_username ?? "TBD"]],
  );

  byId("rotation-schedule").innerHTML = table(
    ["User", "Week"],
    rotation.map((item) => [item.username, item.deadline ? formatDateShort(item.deadline) : "—"]),
  );

  byId("turn-status").innerHTML = status(
    isTurn ? "It is your turn to pick and submit the next happy hour location." : "It is not currently your turn.",
  );

  if (isTurn) {
    // Compute next Friday at 4 PM Pacific.
    // Pacific offset: PST = UTC-8, PDT = UTC-7.
    // Detect DST by checking the offset of that specific Friday.
    const nextFriday = (() => {
      const now = new Date();
      const day = now.getUTCDay();
      const daysUntilFriday = (5 - day + 7) % 7 || 7;
      const fri = new Date(now);
      fri.setUTCDate(fri.getUTCDate() + daysUntilFriday);
      // Create a date at noon Pacific on that Friday to determine DST offset
      const testDate = new Date(fri.toISOString().split("T")[0] + "T12:00:00-08:00");
      // getTimezoneOffset is in minutes; we use Intl to detect America/Los_Angeles offset
      const pacificHour = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", hour12: false }).format(testDate);
      const isPDT = parseInt(pacificHour) === 13; // noon PST = 12, noon PDT = 13 (since we fed -08:00)
      const utcHour = isPDT ? 23 : 24; // 4 PM PDT = 23:00 UTC, 4 PM PST = 00:00 UTC (next day)
      fri.setUTCHours(utcHour % 24, 0, 0, 0);
      if (utcHour === 24) fri.setUTCDate(fri.getUTCDate() + 1);
      return fri.toISOString();
    })();

    byId("create-event-form").innerHTML = `
      <p style="font-size: 0.9em; color: #aaa; margin-bottom: 12px;">Happy hour is always scheduled for Friday at 4:00 PM Pacific.</p>
      <label>Location</label>
      <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px;">
        <select id="location-select" style="flex: 1;">
          ${locations.filter(l => !l.closed).map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}
          <option value="new">➕ Add New Location...</option>
        </select>
        <button type="button" id="random-location-btn">🎲 Random</button>
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
    
    locationSelect.addEventListener("change", () => {
      newLocationFields.style.display = locationSelect.value === "new" ? "block" : "none";
    });
    
    byId("random-location-btn")?.addEventListener("click", () => {
      const openLocations = locations.filter(l => !l.closed);
      if (openLocations.length > 0) {
        const randomLocation = openLocations[Math.floor(Math.random() * openLocations.length)];
        locationSelect.value = String(randomLocation.id);
        newLocationFields.style.display = "none";
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
            // Parse address string into structured fields (best-effort)
            ...parseAddress(address),
          });
          locationId = newLoc.id;
        } else {
          locationId = Number(locationSelect.value);
        }
        const event = await api.createEvent({ location_id: locationId, description, when: nextFriday });
        byId("happyhour-result").innerHTML = status(`Happy hour scheduled at ${event.location_name} for ${formatDate(event.when)}`);
      } catch (err: any) {
        byId("happyhour-result").innerHTML = status(`Error: ${err.message}`);
      }
    });
  } else {
    byId("create-event-form").innerHTML = "";
  }

  // Render initial batch of locations (client-side — locations are needed in full for the dropdown)
  const initialLocations = locations.slice(0, BATCH_SIZE);
  byId("locations-list").innerHTML = table(
    ["Name", "City", "Closed"],
    initialLocations.map((item) => [item.name, item.city, String(item.closed)]),
  );

  setupInfiniteScroll({
    scrollContainerId: "locations-scroll-container",
    sentinelId: "locations-sentinel",
    statusId: "locations-status",
    batchSize: BATCH_SIZE,
    totalItems: locations.length,
    onLoadMore: (start, end) => {
      const nextBatch = locations.slice(start, end);
      appendTableRows("locations-list", nextBatch.map((item) => [item.name, item.city, String(item.closed)]));
    }
  });

  // Render initial page of events (server-paginated)
  byId("events-list").innerHTML = table(
    ["When", "Location", "Chosen By"],
    eventsPage.items.map((item) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]),
  );

  setupServerPaginatedScroll({
    scrollContainerId: "events-scroll-container",
    sentinelId: "events-sentinel",
    statusId: "events-status",
    pageSize: BATCH_SIZE,
    totalItems: eventsPage.total,
    fetchPage: async (page) => {
      const resp = await api.getEventsPage(page, BATCH_SIZE);
      return resp.items.map((item) => [formatDate(item.when), item.location_name, item.tyrant_username ?? "TBD"]);
    },
  });
}

export async function renderAdmin() {
  const result = byId("admin-claims-result");
  const container = byId("admin-claims-list");

  async function loadClaims() {
    try {
      const claims = await api.getClaimRequests();
      if (claims.length === 0) {
        container.innerHTML = "<p>No pending claim requests.</p>";
        return;
      }
      container.innerHTML = claims.map((c) => `
        <div class="card" style="margin-bottom: 12px; padding: 16px;">
          <p><strong>Requester:</strong> ${esc(c.requester_name)} (${esc(c.requester_email ?? "no email")})</p>
          <p><strong>Provider:</strong> ${esc(c.requester_provider)}</p>
          <p><strong>Target account:</strong> ${esc(c.target_username)} (#${c.target_account_id})</p>
          <p><strong>Status:</strong> ${esc(c.status)}</p>
          <p><strong>Submitted:</strong> ${c.created_at ? formatDate(c.created_at) : "unknown"}</p>
          ${c.status === "pending" ? `
            <div style="margin-top: 8px;">
              <button type="button" class="approve-btn" data-claim-id="${c.id}" style="margin-right: 8px;">Approve</button>
              <button type="button" class="deny-btn" data-claim-id="${c.id}">Deny</button>
            </div>
          ` : `<p><strong>Resolved:</strong> ${c.resolved_at ? formatDate(c.resolved_at) : ""}</p>`}
        </div>
      `).join("");

      container.querySelectorAll(".approve-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.claimId);
          try {
            await api.reviewClaimRequest(id, { decision: "approve" });
            result.innerHTML = status("Claim approved.");
            await loadClaims();
          } catch (err: any) {
            result.innerHTML = status(`Error: ${err.message}`);
          }
        });
      });

      container.querySelectorAll(".deny-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = Number((btn as HTMLElement).dataset.claimId);
          try {
            await api.reviewClaimRequest(id, { decision: "deny" });
            result.innerHTML = status("Claim denied.");
            await loadClaims();
          } catch (err: any) {
            result.innerHTML = status(`Error: ${err.message}`);
          }
        });
      });
    } catch (err: any) {
      container.innerHTML = status(`Error loading claims: ${err.message}`);
    }
  }

  await loadClaims();
}
