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
    };
  },

  async getMealbotSummary(): Promise<MealSummary> {
    // Backend returns nested: {user: {otherUser: {"incoming-credits": N, "outgoing-credits": N}}}
    // We need to compute per-user net balance (total incoming - total outgoing).
    const raw = await api.getMealbotSummary();
    const balances: { user: string; net: number }[] = [];
    for (const [user, others] of Object.entries(raw)) {
      let totalIn = 0;
      let totalOut = 0;
      for (const counters of Object.values(others)) {
        totalIn += counters["incoming-credits"] ?? 0;
        totalOut += counters["outgoing-credits"] ?? 0;
      }
      balances.push({ user, net: totalIn - totalOut });
    }
    balances.sort((a, b) => b.net - a.net);
    return { balances };
  },

  async getMealbotLedger(): Promise<MealRecord[]> {
    const records = await api.getMealbotLedger();
    return records.map((r) => ({
      payer: r.payer,
      recipient: r.recipient,
      credits: r.credits,
      date: r.date,
    }));
  },

  async getMyMealbotLedger(): Promise<MealRecord[]> {
    const records = await api.getMyMealbotLedger();
    return records.map((r) => ({
      payer: r.payer,
      recipient: r.recipient,
      credits: r.credits,
      date: r.date,
    }));
  },

  async getIndividualizedSummary(): Promise<IndividualizedSummary> {
    // Build from the personal ledger
    const records = await api.getMyMealbotLedger();
    const profile = await api.getProfile();
    const username = profile.username;

    const inMap = new Map<string, number>();
    const outMap = new Map<string, number>();

    for (const r of records) {
      if (r.recipient === username) {
        inMap.set(r.payer, (inMap.get(r.payer) ?? 0) + r.credits);
      }
      if (r.payer === username) {
        outMap.set(r.recipient, (outMap.get(r.recipient) ?? 0) + r.credits);
      }
    }

    return {
      incoming: Array.from(inMap.entries())
        .map(([from, credits]) => ({ from, credits }))
        .sort((a, b) => b.credits - a.credits),
      outgoing: Array.from(outMap.entries())
        .map(([to, credits]) => ({ to, credits }))
        .sort((a, b) => b.credits - a.credits),
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
