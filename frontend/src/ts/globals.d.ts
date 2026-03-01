declare module "*.json";

/**
 * Global variables injected by the Jinja2 base template.
 */
interface Window {
  /** Backend API base URL (empty string when using the BFF proxy). */
  __API_BASE: string;
  /** When `true`, the frontend uses mock data instead of live API calls. */
  __USE_MOCK: boolean;
  /** When `true`, the app is running in development mode. */
  __DEV_MODE: boolean;
}
