/**
 * Data provider facade — selects mock or live backend based on config.
 *
 * Mock mode is only available in dev mode (both __USE_MOCK and __DEV_MODE
 * must be true).  In production builds, mockData.ts is replaced with a
 * stub that throws at runtime.
 */
import type { Profile, MealRecord, MealSummary, IndividualizedSummary, HappyHourEvent, RotationMember, HappyHourLocation } from "../types.js";

export interface DataProvider {
  getProfile(): Promise<Profile>;
  getMealbotSummary(): Promise<MealSummary>;
  getMealbotLedger(): Promise<MealRecord[]>;
  getMyMealbotLedger(): Promise<MealRecord[]>;
  getIndividualizedSummary(): Promise<IndividualizedSummary>;
  getUpcomingHappyHour(): Promise<HappyHourEvent>;
  getPastHappyHours(): Promise<HappyHourEvent[]>;
  getRotation(): Promise<RotationMember[]>;
  getLocations(): Promise<HappyHourLocation[]>;
  getEvents(): Promise<HappyHourEvent[]>;
  isCurrentUserTurn(): Promise<boolean>;
  getAllUsers(): Promise<string[]>;
}

const useMock = (window as any).__USE_MOCK === true && (window as any).__DEV_MODE === true;

async function loadProvider(): Promise<DataProvider> {
  if (useMock) {
    const { mockDataProvider } = await import("./mockData.js");
    return mockDataProvider;
  }
  const { liveDataProvider } = await import("./liveData.js");
  return liveDataProvider;
}

const _provider = loadProvider();

/** Resolved data provider — use this everywhere in pages. */
export const dataProvider: DataProvider = {
  getProfile: () => _provider.then(p => p.getProfile()),
  getMealbotSummary: () => _provider.then(p => p.getMealbotSummary()),
  getMealbotLedger: () => _provider.then(p => p.getMealbotLedger()),
  getMyMealbotLedger: () => _provider.then(p => p.getMyMealbotLedger()),
  getIndividualizedSummary: () => _provider.then(p => p.getIndividualizedSummary()),
  getUpcomingHappyHour: () => _provider.then(p => p.getUpcomingHappyHour()),
  getPastHappyHours: () => _provider.then(p => p.getPastHappyHours()),
  getRotation: () => _provider.then(p => p.getRotation()),
  getLocations: () => _provider.then(p => p.getLocations()),
  getEvents: () => _provider.then(p => p.getEvents()),
  isCurrentUserTurn: () => _provider.then(p => p.isCurrentUserTurn()),
  getAllUsers: () => _provider.then(p => p.getAllUsers()),
};
