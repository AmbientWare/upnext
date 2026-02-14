/**
 * Lightweight auth store backed by localStorage.
 *
 * The API key is stored in localStorage and exposed via getter/setter.
 * Components react to changes through the AuthProvider context.
 */

const STORAGE_KEY = "upnext_api_key";

export function getStoredApiKey(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setStoredApiKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key);
}

export function clearStoredApiKey(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * Append `?token=<key>` to a URL for SSE streams.
 * EventSource doesn't support custom headers, so the backend
 * also accepts the API key as a query parameter.
 */
export function withAuthToken(url: string): string {
  const key = getStoredApiKey();
  if (!key) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}token=${encodeURIComponent(key)}`;
}
