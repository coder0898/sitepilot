import { supabase, supabaseConfigured } from "../lib/supabase";
import { api } from "./client";

function ensureConfigured() {
  if (!supabaseConfigured) throw new Error("Supabase Auth is not configured for this build.");
}

function unwrap(result) {
  if (result.error) throw new Error(result.error.message);
  return result.data;
}

export const authApi = {
  async login(email, password) {
    ensureConfigured();
    return unwrap(await supabase.auth.signInWithPassword({ email, password }));
  },
  async requestReset(email) {
    ensureConfigured();
    const redirectTo = `${window.location.origin}/?view=reset-password`;
    unwrap(await supabase.auth.resetPasswordForEmail(email, { redirectTo }));
    return { message: "If this account exists, Supabase has sent a recovery email." };
  },
  async verifyRecoveryToken(tokenHash) {
    ensureConfigured();
    return unwrap(await supabase.auth.verifyOtp({ token_hash: tokenHash, type: "recovery" }));
  },
  async consumeAccessVerificationCallback() {
    ensureConfigured();
    const query = new URLSearchParams(window.location.search);
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const callbackError = fragment.get("error_description") || query.get("error_description");
    if (callbackError) throw new Error(callbackError.replaceAll("+", " "));
    // Server-issued Supabase magic links return an implicit session in the URL
    // fragment. The browser client otherwise uses PKCE, so consume this callback
    // explicitly instead of depending on automatic URL detection.
    const accessToken = fragment.get("access_token");
    const refreshToken = fragment.get("refresh_token");
    if (accessToken && refreshToken) {
      const result = unwrap(await supabase.auth.setSession({
        access_token: accessToken,
        refresh_token: refreshToken,
      }));
      window.history.replaceState({}, "", window.location.pathname + "?view=verify-access");
      return result;
    }
    // Keep compatibility with PKCE links if hosted Supabase later returns a code.
    const code = query.get("code");
    if (code) {
      let result;
      try {
        result = unwrap(await supabase.auth.exchangeCodeForSession(code));
      } catch (error) {
        if (error.message?.toLowerCase().includes("code verifier")) {
          throw new Error("This verification link was created by an older sign-in flow. Request a fresh verification email and open only the newest link.", { cause: error });
        }
        throw error;
      }
      window.history.replaceState({}, "", window.location.pathname + "?view=verify-access");
      return result;
    }
    const { data, error } = await supabase.auth.getSession();
    if (error) throw new Error(error.message);
    return data;
  },
  async updatePassword(password) {
    ensureConfigured();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) throw new Error("This password setup session is missing or expired. Request a new link.");
    return unwrap(await supabase.auth.updateUser({ password }));
  },
  completeActivation: () => api("/api/auth/complete-activation", { method: "POST" }),
  async logout() {
    ensureConfigured();
    const { error } = await supabase.auth.signOut();
    if (error) throw new Error(error.message);
  },
  getSession: () => supabase.auth.getSession(),
  onAuthStateChange: callback => supabase.auth.onAuthStateChange(callback),
};
