/**
 * Authoritative API Client with automatic JWT Bearer token attachment,
 * transparent token refresh on 401, session management, and logout cleanup.
 */

interface TokenSession {
  accessToken: string;
  refreshToken: string;
  role: string;
  email: string;
}

let currentSession: TokenSession | null = null;

// Load session from sessionStorage (memory-safe per browser session)
try {
  const saved = sessionStorage.getItem('auth_session');
  if (saved) {
    currentSession = JSON.parse(saved);
  }
} catch (e) {
  // Session storage unavailable
}

export function getSession(): TokenSession | null {
  return currentSession;
}

export function setSession(session: TokenSession | null) {
  currentSession = session;
  if (session) {
    sessionStorage.setItem('auth_session', JSON.stringify(session));
  } else {
    sessionStorage.removeItem('auth_session');
  }
}

export async function login(email: string, password: string): Promise<TokenSession> {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Authentication failed' }));
    throw new Error(err.detail || 'Authentication failed');
  }

  const data = await res.json();
  const session: TokenSession = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    role: data.role,
    email,
  };
  setSession(session);
  return session;
}

export async function logout(): Promise<void> {
  if (currentSession?.accessToken) {
    try {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${currentSession.accessToken}` },
      });
    } catch (e) {
      // Best-effort remote notification
    }
  }
  setSession(null);
}

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

async function refreshAccessToken(): Promise<string | null> {
  if (!currentSession?.refreshToken) {
    setSession(null);
    return null;
  }

  try {
    const res = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: currentSession.refreshToken }),
    });

    if (!res.ok) {
      setSession(null);
      return null;
    }

    const data = await res.json();
    currentSession.accessToken = data.access_token;
    currentSession.refreshToken = data.refresh_token;
    setSession(currentSession);
    return data.access_token;
  } catch (e) {
    setSession(null);
    return null;
  }
}

/**
 * Authoritative fetch wrapper attaching Authorization Bearer tokens and handling 401 refreshes.
 */
export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});

  if (currentSession?.accessToken) {
    headers.set('Authorization', `Bearer ${currentSession.accessToken}`);
  }

  let response = await fetch(input, { ...init, headers });

  // If 401 Unauthorized, attempt refresh once
  if (response.status === 401 && currentSession?.refreshToken) {
    if (!isRefreshing) {
      isRefreshing = true;
      const newToken = await refreshAccessToken();
      isRefreshing = false;

      if (newToken) {
        onTokenRefreshed(newToken);
        headers.set('Authorization', `Bearer ${newToken}`);
        return fetch(input, { ...init, headers });
      } else {
        // Refresh failed, return original 401 response
        return response;
      }
    } else {
      // Await active refresh
      return new Promise((resolve) => {
        refreshSubscribers.push((newToken: string) => {
          headers.set('Authorization', `Bearer ${newToken}`);
          resolve(fetch(input, { ...init, headers }));
        });
      });
    }
  }

  return response;
}
