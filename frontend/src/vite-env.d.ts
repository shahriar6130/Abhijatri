/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_API_DIRECT?: string;
  readonly VITE_DEFAULT_TIMEZONE?: string;
  readonly VITE_ALLOWED_BACKEND_HOSTS?: string;
  readonly VITE_REVIEW_CATEGORY_RATINGS?: string;
  readonly VITE_TURNSTILE_SITE_KEY?: string;
}

/** The subset of Cloudflare Turnstile's explicit-render API this app uses. */
interface TurnstileApi {
  render(
    container: HTMLElement,
    options: {
      sitekey: string;
      action?: string;
      language?: string;
      callback?: (token: string) => void;
      'expired-callback'?: () => void;
      'error-callback'?: () => void;
    },
  ): string;
  reset(widgetId?: string): void;
  remove(widgetId: string): void;
}

interface Window {
  turnstile?: TurnstileApi;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

