/**
 * Live data provider — fetches real data from the vibe-coded FastAPI backend.
 * Same interface as the mock data provider so pages work with either.
 */
import * as api from "./apiClient.js";
import { decodeClaims } from "../types.js";
import type { Profile, MealRecord, MealSummary, IndividualizedSummary, HappyHourEvent, RotationMember, HappyHourLocation } from "../types.js";

export const liveDataProvider = {

  async getProfile(): Promise<Profile> {
    const raw = await api.getProfile();
    return {
      id: raw.id,
      username: raw.username,
      oidc_email: raw.oidc_email,
      email: raw.email,
      phone: raw.phone,
      phone_provider: raw.phone_provider,
      claims: raw.claims,
      theme: raw.theme,
      status: raw.status,
    };
  },

  async getMealbotSummary(): Promise<MealSummary> {
    // Backend returns nested: {user: {otherUser: {"incoming-credits": N, "outgoing-credits": N}}}
    // Extract the current user's row so balances are relative to *me*, not global.
    const [raw, profile] = await Promise.all([api.getMealbotSummary(), api.getProfile()]);
    const myData = raw[profile.username] ?? {};
    const balances: { user: string; net: number }[] = [];
    for (const [otherUser, counters] of Object.entries(myData)) {
      // outgoing = I paid for them → they owe me
      // incoming = they paid for me → I owe them
      const net = (counters["outgoing-credits"] ?? 0) - (counters["incoming-credits"] ?? 0);
      balances.push({ user: otherUser, net });
    }
    balances.sort((a, b) => b.net - a.net);
    return { balances };
  },

  async getMealbotLedger(): Promise<MealRecord[]> {
    const records = await api.getMealbotLedger();
    return records.map((r) => ({
      id: r.id,
      payer: r.payer,
      recipient: r.recipient,
      credits: r.credits,
      date: r.date,
    }));
  },

  async getMyMealbotLedger(): Promise<MealRecord[]> {
    const records = await api.getMyMealbotLedger();
    return records.map((r) => ({
      id: r.id,
      payer: r.payer,
      recipient: r.recipient,
      credits: r.credits,
      date: r.date,
    }));
  },

  async getIndividualizedSummary(): Promise<IndividualizedSummary> {
    // Build net balances from the personal ledger.
    // Positive net = they owe you, negative net = you owe them.
    const records = await api.getMyMealbotLedger();
    const profile = await api.getProfile();
    const username = profile.username;

    const netMap = new Map<string, number>();

    for (const r of records) {
      if (r.payer === username) {
        // I paid for them → they owe me
        netMap.set(r.recipient, (netMap.get(r.recipient) ?? 0) + r.credits);
      }
      if (r.recipient === username) {
        // They paid for me → I owe them
        netMap.set(r.payer, (netMap.get(r.payer) ?? 0) - r.credits);
      }
    }

    const incoming: { from: string; credits: number }[] = [];
    const outgoing: { to: string; credits: number }[] = [];

    for (const [user, net] of netMap.entries()) {
      if (net > 0) {
        incoming.push({ from: user, credits: net });
      } else if (net < 0) {
        outgoing.push({ to: user, credits: -net });
      }
    }

    return {
      incoming: incoming.sort((a, b) => b.credits - a.credits),
      outgoing: outgoing.sort((a, b) => b.credits - a.credits),
    };
  },

  async getUpcomingHappyHour(): Promise<HappyHourEvent> {
    const ev = await api.getUpcomingEvent();
    if (!ev) {
      return {
        id: 0,
        description: null,
        when: "",
        location_id: 0,
        location_name: "TBD",
        tyrant_username: null,
        auto_selected: false,
        current_tyrant_username: null,
        current_tyrant_deadline: null,
      };
    }
    return ev;
  },

  async getPastHappyHours(): Promise<HappyHourEvent[]> {
    const all = await api.getEvents();
    const now = new Date();
    return all
      .filter((e) => new Date(e.when) < now)
      .sort((a, b) => new Date(b.when).getTime() - new Date(a.when).getTime());
  },

  async getRotation(): Promise<RotationMember[]> {
    const schedule = await api.getRotation();
    return schedule.members;
  },

  async getLocations(): Promise<HappyHourLocation[]> {
    const locs = await api.getLocations();
    return locs.map((l) => ({
      id: l.id,
      name: l.name,
      city: l.city,
      closed: l.closed,
      illegal: l.illegal,
      url: l.url,
      address_raw: l.address_raw,
    }));
  },

  async getEvents(): Promise<HappyHourEvent[]> {
    const evts = await api.getEvents();
    return evts.sort((a, b) => new Date(b.when).getTime() - new Date(a.when).getTime());
  },

  async isCurrentUserTurn(): Promise<boolean> {
    const profile = await api.getProfile();
    const upcoming = await api.getUpcomingEvent();
    if (!upcoming) return false;
    return upcoming.current_tyrant_username === profile.username;
  },

  async getAllUsers(): Promise<string[]> {
    // Derive user list from the mealbot summary (requires MEALBOT claim, not HAPPY_HOUR)
    const raw = await api.getMealbotSummary();
    return Object.keys(raw).sort();
  },
};
