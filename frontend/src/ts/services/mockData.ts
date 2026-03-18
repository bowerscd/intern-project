import { HappyHourEvent, HappyHourLocation, IndividualizedSummary, MealRecord, Profile, RotationMember, ClaimFlags } from "../types.js";
import type { DataProvider } from "./dataProvider.js";

export const mockProfile: Profile = {
  id: 1,
  username: "demo.user",
  oidc_email: "demo@example.com",
  email: "demo@example.com",
  phone: "5551112233",
  phone_provider: "verizon",
  claims: ClaimFlags.BASIC | ClaimFlags.MEALBOT | ClaimFlags.HAPPY_HOUR | ClaimFlags.HAPPY_HOUR_TYRANT,
  theme: "default",
  status: "active",
};

// Generate 120 meal records
const generateMealRecords = (): MealRecord[] => {
  const users = ["demo.user", "alex", "sam", "morgan", "taylor", "jordan", "casey", "riley", "avery", "quinn", "drew", "skyler", "charlie", "jamie", "reese"];
  const records: MealRecord[] = [];
  const startDate = new Date("2025-08-01T12:00:00Z");
  
  for (let i = 0; i < 120; i++) {
    const payer = users[Math.floor(Math.random() * users.length)];
    let recipient = users[Math.floor(Math.random() * users.length)];
    while (recipient === payer) {
      recipient = users[Math.floor(Math.random() * users.length)];
    }
    const credits = Math.floor(Math.random() * 5) + 1;
    const d = new Date(startDate.getTime() + i * 24 * 60 * 60 * 1000 + Math.random() * 12 * 60 * 60 * 1000);
    records.push({ id: i + 1, payer, recipient, credits, date: d.toISOString() });
  }
  
  return records.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
};

export const mockMealbotLedger: MealRecord[] = generateMealRecords();

// Calculate individualized summary for demo.user
const calculateIndividualized = (records: MealRecord[], username: string): IndividualizedSummary => {
  const netMap = new Map<string, number>();

  records.forEach(record => {
    if (record.payer === username) {
      netMap.set(record.recipient, (netMap.get(record.recipient) || 0) + record.credits);
    }
    if (record.recipient === username) {
      netMap.set(record.payer, (netMap.get(record.payer) || 0) - record.credits);
    }
  });

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
};

export const mockIndividualizedSummary: IndividualizedSummary = calculateIndividualized(mockMealbotLedger, "demo.user");

export const mockUpcomingHappyHour: HappyHourEvent = {
  id: 81,
  description: "Friday rooftop happy hour",
  when: "2026-03-06T23:00:00Z",
  location_id: 1,
  location_name: "Skyline Taproom",
  tyrant_username: "demo.user",
  auto_selected: false,
  current_tyrant_username: "demo.user",
  current_tyrant_deadline: "2026-03-04T23:00:00Z",
};

// Generate 80 past happy hours
const generatePastHappyHours = (): HappyHourEvent[] => {
  const locations = ["Skyline Taproom", "Barrel House", "Odd Duck", "Loud Lounge", "The Pearl", "High Wire", "Brass Tap", 
    "Corner Pub", "Moonlight Bar", "Red Lion", "Golden Gate", "Sunset Grill", "Harbor View", "Mountain Peak", 
    "Valley Tavern", "Riverside Inn", "City Lights", "Rooftop Retreat", "Underground Bar", "Beach Club"];
  const users = ["demo.user", "alex", "sam", "morgan", "taylor", "jordan", "casey", "riley", "avery", "quinn"];
  const events: HappyHourEvent[] = [];
  const startDate = new Date("2024-06-07T23:00:00Z"); // Start from June 2024, ~80 weeks ago
  
  for (let i = 0; i < 80; i++) {
    const eventDate = new Date(startDate.getTime() + i * 7 * 24 * 60 * 60 * 1000);
    events.push({
      id: i + 1,
      description: "Weekly happy hour",
      when: eventDate.toISOString(),
      location_id: (i % 20) + 1,
      location_name: locations[Math.floor(Math.random() * locations.length)],
      tyrant_username: users[i % users.length],
      auto_selected: false,
      current_tyrant_username: null,
      current_tyrant_deadline: null,
    });
  }
  
  return events.reverse(); // Most recent first
};

export const mockPastHappyHours: HappyHourEvent[] = generatePastHappyHours();

// Generate rotation with 25 members
const generateRotation = (): RotationMember[] => {
  const users = ["demo.user", "alex", "sam", "morgan", "taylor", "jordan", "casey", "riley", "avery", "quinn", 
    "drew", "skyler", "charlie", "jamie", "reese", "parker", "emerson", "hayden", "cameron", "peyton",
    "rowan", "finley", "sage", "river", "dakota"];
  const startDate = new Date("2026-03-05T12:00:00Z");
  const now = new Date();
  
  return users.map((username, index) => ({
    position: index + 1,
    username,
    status: index === 0 ? "PENDING" : "WAITING",
    deadline: new Date(startDate.getTime() + index * 7 * 24 * 60 * 60 * 1000).toISOString(),
  })).filter(member => new Date(member.deadline!) > now); // Only show upcoming turns
};

export const mockRotation: RotationMember[] = generateRotation();

// Generate 50 locations across multiple cities
const generateLocations = (): HappyHourLocation[] => {
  const locationData = [
    { name: "Skyline Taproom", city: "Austin", closed: false },
    { name: "Barrel House", city: "Austin", closed: false },
    { name: "Odd Duck", city: "Austin", closed: false },
    { name: "The Pearl", city: "Austin", closed: true },
    { name: "High Wire", city: "Austin", closed: false },
    { name: "Brass Tap", city: "San Francisco", closed: false },
    { name: "Corner Pub", city: "San Francisco", closed: false },
    { name: "Moonlight Bar", city: "San Francisco", closed: false },
    { name: "Red Lion", city: "Portland", closed: false },
    { name: "Golden Gate", city: "Portland", closed: true },
    { name: "Sunset Grill", city: "Seattle", closed: false },
    { name: "Harbor View", city: "Seattle", closed: false },
    { name: "Mountain Peak", city: "Denver", closed: false },
    { name: "Valley Tavern", city: "Denver", closed: false },
    { name: "Riverside Inn", city: "Denver", closed: true },
    { name: "City Lights", city: "Chicago", closed: false },
    { name: "Rooftop Retreat", city: "Chicago", closed: false },
    { name: "Underground Bar", city: "New York", closed: false },
    { name: "Beach Club", city: "Miami", closed: false },
    { name: "Loud Lounge", city: "Austin", closed: false },
    { name: "Velvet Room", city: "Boston", closed: false },
    { name: "Iron Horse", city: "Boston", closed: true },
    { name: "The Anchor", city: "San Diego", closed: false },
    { name: "Neon Nights", city: "Las Vegas", closed: false },
    { name: "Desert Rose", city: "Phoenix", closed: false },
    { name: "Copper Door", city: "Phoenix", closed: false },
    { name: "Silver Spoon", city: "Dallas", closed: true },
    { name: "Blue Moon", city: "Nashville", closed: false },
    { name: "Green Lantern", city: "Atlanta", closed: false },
    { name: "Yellow Submarine", city: "Minneapolis", closed: false },
    { name: "Purple Haze", city: "Minneapolis", closed: false },
    { name: "Orange Crush", city: "Orlando", closed: true },
    { name: "Pink Flamingo", city: "Tampa", closed: false },
    { name: "Black Cat", city: "Baltimore", closed: false },
    { name: "White Tiger", city: "Detroit", closed: false },
    { name: "Gray Wolf", city: "Milwaukee", closed: false },
    { name: "Brown Bear", city: "Kansas City", closed: true },
    { name: "Crimson Crow", city: "St. Louis", closed: false },
    { name: "Indigo Owl", city: "Cincinnati", closed: false },
    { name: "Turquoise Turtle", city: "Columbus", closed: false },
    { name: "Magenta Moose", city: "Indianapolis", closed: false },
    { name: "Chartreuse Cheetah", city: "Charlotte", closed: false },
    { name: "Coral Cougar", city: "Raleigh", closed: true },
    { name: "Emerald Eagle", city: "Richmond", closed: false },
    { name: "Ruby Raven", city: "Pittsburgh", closed: false },
    { name: "Sapphire Sparrow", city: "Cleveland", closed: false },
    { name: "Amber Alligator", city: "Jacksonville", closed: false },
    { name: "Jade Jaguar", city: "Memphis", closed: false },
    { name: "Pearl Panther", city: "Louisville", closed: true },
    { name: "Diamond Dragon", city: "Oklahoma City", closed: false },
  ];
  
  return locationData.map((loc, index) => ({
    id: index + 1,
    illegal: false,
    url: null,
    address_raw: `${100 + index} Main St, ${loc.city}`,
    ...loc,
  }));
};

export const mockLocations: HappyHourLocation[] = generateLocations();

export const mockIsCurrentUserTurn = true;

export const mockAllUsers = ["demo.user", "alex", "sam", "morgan", "taylor", "jordan", "casey", "riley", 
  "avery", "quinn", "drew", "skyler", "charlie", "jamie", "reese", "parker", "emerson", "hayden", 
  "cameron", "peyton", "rowan", "finley", "sage", "river", "dakota"];

/** Mock data provider — same interface as liveDataProvider. */
export const mockDataProvider: DataProvider = {
  async getProfile() { return mockProfile; },
  async getMealbotLedger() { return mockMealbotLedger; },
  async getMyMealbotLedger() {
    return mockMealbotLedger.filter(r => r.payer === "demo.user" || r.recipient === "demo.user");
  },
  async getIndividualizedSummary() { return mockIndividualizedSummary; },
  async getUpcomingHappyHour() { return mockUpcomingHappyHour; },
  async getPastHappyHours() { return mockPastHappyHours; },
  async getRotation() { return mockRotation; },
  async getLocations() { return mockLocations; },
  async getEvents() { return [mockUpcomingHappyHour, ...mockPastHappyHours]; },
  async isCurrentUserTurn() { return mockIsCurrentUserTurn; },
  async getAllUsers() { return mockAllUsers; },
};
