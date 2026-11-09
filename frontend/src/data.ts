import type { JsonObject, JsonValue } from './api';
export const object = (value: unknown): JsonObject =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : {};
export const list = (value: unknown): JsonValue[] =>
  Array.isArray(value) ? (value as JsonValue[]) : [];
export const records = (value: unknown): JsonObject[] => list(value).map(object);
export const text = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : typeof value === 'number' ? String(value) : fallback;
export const number = (value: unknown, fallback = 0): number => {
  const candidate =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && /^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)
        ? Number(value)
        : NaN;
  return Number.isFinite(candidate) ? candidate : fallback;
};
export const humanize = (value: string): string => {
  const s = value.replaceAll('_', ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
};
export const strings = (value: unknown): string[] =>
  list(value)
    .map((v) => text(v))
    .filter(Boolean);
export function safeHref(value: unknown, fallback = '#'): string {
  const url = text(value);
  if ((url.startsWith('/') && !url.startsWith('//')) || url.startsWith('#')) return url;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:') return url;
  } catch {
    /* Unsupported source link. */
  }
  return fallback;
}
