const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`;

export function assetUrl(path) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

function token() {
  return localStorage.getItem("siteops_token");
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (token()) headers.Authorization = `Bearer ${token()}`;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(data?.detail || data?.message || "Something went wrong");
  return data;
}

export function saveSession(data) {
  localStorage.setItem("siteops_token", data.token);
  localStorage.setItem("siteops_user", JSON.stringify(data.user));
}

export function clearSession() {
  localStorage.removeItem("siteops_token");
  localStorage.removeItem("siteops_user");
}

export function cachedUser() {
  try {
    return JSON.parse(localStorage.getItem("siteops_user") || "null");
  } catch {
    return null;
  }
}
