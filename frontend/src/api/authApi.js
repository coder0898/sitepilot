import { supabase, supabaseConfigured } from "../lib/supabase";

function ensureConfigured() {
  if (!supabaseConfigured) throw new Error("Supabase Auth is not configured for this build.");
}

export const authApi = {
  async signInWithGoogle() {
    ensureConfigured();
    // Pinned rather than window.location.origin - otherwise this would send
    // the post-login bounce back to whatever origin triggered it (e.g.
    // localhost, if triggered during local dev against prod).
    const redirectTo = `${import.meta.env.VITE_FRONTEND_URL || window.location.origin}/`;
    const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo } });
    if (error) throw new Error(error.message);
  },
  async logout() {
    ensureConfigured();
    const { error } = await supabase.auth.signOut();
    if (error) throw new Error(error.message);
  },
  getSession: () => supabase.auth.getSession(),
  onAuthStateChange: callback => supabase.auth.onAuthStateChange(callback),
};
