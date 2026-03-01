export type Profile = {
  id: number;
  username: string;
  email: string | null;
  phone: string | null;
  phone_provider: string;
  claims: number;
};

/** Bitmask values matching backend AccountClaims IntFlag. */
export const ClaimFlags: Record<string, number> = {
  BASIC: 1,
  ADMIN: 2,
  MEALBOT: 4,
  COOKBOOK: 8,
  HAPPY_HOUR: 16,
  HAPPY_HOUR_TYRANT: 32,
};

/** Decode a bitmask integer into an array of claim name strings. */
export function decodeClaims(bitmask: number): string[] {
  return Object.entries(ClaimFlags)
    .filter(([, bit]) => (bitmask & bit) !== 0)
    .map(([name]) => name);
}

/** Encode an array of claim name strings into a bitmask integer. */
export function encodeClaims(names: string[]): number {
  return names.reduce((acc, name) => acc | (ClaimFlags[name] ?? 0), 0);
}

export type MealRecord = {
  payer: string;
  recipient: string;
  credits: number;
  date: string;
};

export type MealSummary = {
  balances: Array<{ user: string; net: number }>;
};

export type IndividualizedSummary = {
  incoming: Array<{ from: string; credits: number }>;
  outgoing: Array<{ to: string; credits: number }>;
};

export type HappyHourEvent = {
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

export type RotationMember = {
  position: number;
  username: string;
  status: string;
  deadline: string | null;
};

export type HappyHourLocation = {
  id: number;
  name: string;
  city: string;
  closed: boolean;
  illegal: boolean;
  url: string | null;
  address_raw: string;
};
