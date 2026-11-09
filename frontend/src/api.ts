import { QueryClient, useQuery } from '@tanstack/react-query';
import { useLocation, useNavigationType } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import type { components } from './generated/api';

export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export interface JsonObject {
  [key: string]: JsonValue | undefined;
}
export type UiPage = components['schemas']['UiPage'];
export type Fields = NonNullable<components['schemas']['UiAction']['fields']>;
export type ActionResponse = UiPage | components['schemas']['UiRedirect'];

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchInterval: false,
      networkMode: 'always',
    },
    mutations: { retry: false, networkMode: 'always' },
  },
});
export const pageKey = (path: string) => ['page', path] as const;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public page?: UiPage,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function isPage(value: unknown): value is UiPage {
  return (
    !!value &&
    typeof value === 'object' &&
    'page' in value &&
    typeof value.page === 'string' &&
    'data' in value &&
    !!value.data &&
    typeof value.data === 'object' &&
    !Array.isArray(value.data) &&
    'title' in value &&
    typeof value.title === 'string'
  );
}

function uiUrl(path: string) {
  if (!path.startsWith('/') || path.startsWith('//'))
    throw new Error('Use a local Reading Room address.');
  return path.startsWith('/api/') ? path : '/api/ui' + path;
}

async function failure(response: Response): Promise<never> {
  const payload: unknown = await response.json().catch(() => null);
  const page = isPage(payload) ? payload : undefined;
  let message = page?.data.error || page?.data.message;
  if (
    payload &&
    typeof payload === 'object' &&
    'error' in payload &&
    typeof payload.error === 'string'
  )
    message = payload.error;
  throw new ApiError(
    typeof message === 'string'
      ? message
      : `The request could not finish (${response.status}). Please try again.`,
    response.status,
    page,
  );
}

export async function apiGet<T = UiPage>(
  path: string,
  signal?: AbortSignal,
  redirects = 0,
): Promise<T> {
  const response = await fetch(uiUrl(path), {
    signal,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) return failure(response);
  const value: unknown = await response.json();
  if (
    value &&
    typeof value === 'object' &&
    'redirect' in value &&
    typeof value.redirect === 'string'
  ) {
    if (redirects >= 5 || !value.redirect.startsWith('/') || value.redirect.startsWith('//'))
      throw new ApiError(
        'That page could not be reopened. Return to the Reading Room and try again.',
        400,
      );
    return apiGet<T>(value.redirect, signal, redirects + 1);
  }
  return value as T;
}

let token: Promise<string> | undefined;
export function csrfToken(): Promise<string> {
  if (!token)
    token = apiGet<{ csrf: string }>('/api/ui/bootstrap')
      .then((value) => {
        if (!value.csrf) throw new Error('The local session could not be opened. Reload the page.');
        return value.csrf;
      })
      .catch((error) => {
        token = undefined;
        throw error;
      });
  return token;
}

async function actionResponse(path: string, fields: Fields): Promise<Response> {
  const csrf = await csrfToken();
  const response = await fetch(uiUrl(path), {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
    },
    body: JSON.stringify({ fields }),
  });
  if (!response.ok) {
    if (response.status === 403) token = undefined;
    return failure(response);
  }
  return response;
}

export async function apiAction(path: string, fields: Fields = {}): Promise<ActionResponse> {
  const response = await actionResponse(path, fields);
  return response.json() as Promise<ActionResponse>;
}

export async function apiDownload(path: string, fields: Fields): Promise<void> {
  const response = await actionResponse(path, fields);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download =
    response.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/)?.[1] ||
    'citation.txt';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function usePage(path?: string) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const restored = useRef('');
  const address = path ?? location.pathname + location.search;
  const query = useQuery({
    queryKey: pageKey(address),
    queryFn: ({ signal }) => apiGet<UiPage>(address, signal),
  });
  useEffect(() => {
    if (!query.data) return;
    document.title = `${query.data.title} · The Reading Room`;
    if (restored.current === location.key) return;
    const frame = requestAnimationFrame(() => {
      restored.current = location.key;
      if (location.hash) {
        let anchor = location.hash.slice(1);
        try {
          anchor = decodeURIComponent(anchor);
        } catch {
          /* Malformed fragments remain harmless. */
        }
        const target = document.getElementById(anchor);
        if (target) {
          target.scrollIntoView();
          if (target instanceof HTMLElement) target.focus({ preventScroll: true });
        }
      } else if (navigationType === 'POP') {
        try {
          const position = JSON.parse(
            sessionStorage.getItem(`reading-room-position:${location.key}`) ?? 'null',
          ) as { y: number; focus: string } | null;
          if (position) {
            document.getElementById(position.focus)?.focus({ preventScroll: true });
            window.scrollTo(0, position.y);
          }
        } catch {
          /* A new navigation does not need a saved position. */
        }
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [query.data, location.key, location.hash, navigationType]);
  return query;
}

export function formFields(form: HTMLFormElement, submitter?: HTMLElement | null): Fields {
  const data = new FormData(form, submitter);
  const fields: Fields = {};
  for (const key of new Set(data.keys())) {
    const values = data.getAll(key).filter((v): v is string => typeof v === 'string');
    fields[key] = values.length > 1 ? values : (values[0] ?? '');
  }
  return fields;
}
