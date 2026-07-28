import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { accessRequestsApi } from "./api/accessRequestsApi";
import { authApi } from "./api/authApi";
import { AccessRequestPage, VerifyAccessPage } from "./features/auth/AccessRequestPages";
import { ForgotPasswordPage, LoginPage, ResetPasswordPage } from "./features/auth/LoginPage";
import { Dashboard } from "./features/dashboard/Dashboard";
import "./styles.css";

function initialView() {
  const requested = new URLSearchParams(window.location.search).get("view");
  const authError = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("error_code");
  if (authError && requested !== "verify-access") return "forgot-password";
  return requested || "login";
}

function initialAuthError() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  if (!params.get("error")) return "";
  if (params.get("error_code") === "otp_expired") {
    return "This password link has expired or was already used. Request a new link and open only the newest email.";
  }
  return params.get("error_description")?.replaceAll("+", " ") || "This authentication link is invalid. Request a new link.";
}


function App() {
  const [user, setUser] = useState(null);
  const [view, setView] = useState(initialView);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(initialAuthError);
  const [message, setMessage] = useState("");
  const [recoveryReady, setRecoveryReady] = useState(false);
  const [verificationReady, setVerificationReady] = useState(false);

  async function loadPortalIdentity(session) {
    if (!session) { setUser(null); return; }
    setUser(await api("/api/me"));
  }

  function navigate(nextView) {
    setError("");
    setMessage("");
    const url = nextView === "login" ? window.location.pathname : `${window.location.pathname}?view=${nextView}`;
    window.history.replaceState({}, "", url);
    setView(nextView);
  }

  useEffect(() => {
    let active = true;
    const entryView = initialView();

    function handleSessionExpired(event) {
      if (!active) return;
      setUser(null);
      setLoading(false);
      setMessage("");
      setError(event.detail?.message || "Your session expired. Sign in again to continue.");
      window.history.replaceState({}, "", window.location.pathname);
      setView("login");
    }

    window.addEventListener("siteops:session-expired", handleSessionExpired);

    async function initializeAuth() {
      try {
        if (entryView === "verify-access") {
          const { session } = await authApi.consumeAccessVerificationCallback();
          if (!session) throw new Error("The verification session is missing. Request a new link and open only the newest email.");
          if (!active) return;
          setVerificationReady(true);
          setView("verify-access");
        } else {
          const { data: { session } } = await authApi.getSession();
          if (!active) return;
          if (entryView === "reset-password") {
            const tokenHash = new URLSearchParams(window.location.search).get("token_hash");
            if (tokenHash) {
              const verified = await authApi.verifyRecoveryToken(tokenHash);
              if (!verified?.session) throw new Error("Supabase did not create a recovery session.");
              if (!active) return;
              setRecoveryReady(true);
              window.history.replaceState({}, "", `${window.location.pathname}?view=reset-password`);
            } else if (session) {
              setRecoveryReady(true);
            } else {
              throw new Error("This password setup link is incomplete or expired.");
            }
          } else {
            await loadPortalIdentity(session);
          }
        }
      } catch (caught) {
        if (!active) return;
        if (entryView === "reset-password") {
          setView("forgot-password");
          setError("This password setup link is invalid, expired, or already used. Request a new link and open only the newest email.");
          window.history.replaceState({}, "", `${window.location.pathname}?view=forgot-password`);
        } else if (entryView === "verify-access") {
          setView("verify-access");
          setVerificationReady(false);
          setError(caught.message || "This verification link is invalid, expired, or already used. Request a new link and open only the newest email.");
          window.history.replaceState({}, "", `${window.location.pathname}?view=verify-access`);
        } else {
          setError(caught.message);
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    initializeAuth();
    const { data: { subscription } } = authApi.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        setRecoveryReady(true);
        setView("reset-password");
        setLoading(false);
      } else if (event === "SIGNED_OUT") {
        setUser(null);
        if (!["verify-access", "request-access"].includes(initialView())) setView("login");
      }
    });
    return () => {
      active = false;
      window.removeEventListener("siteops:session-expired", handleSessionExpired);
      subscription.unsubscribe();
    };
  }, []);

  async function login(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    const form = new FormData(event.currentTarget);
    try {
      const { session } = await authApi.login(form.get("email"), form.get("password"));
      await loadPortalIdentity(session);
    } catch (caught) {
      await authApi.logout().catch(() => {});
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }

  async function requestAccess(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await accessRequestsApi.create(form);
      setMessage("Check your email and open the verification link to submit the request for approval.");
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }

  async function verifyAccess() {
    setError("");
    setLoading(true);
    try {
      await accessRequestsApi.verify();
      sessionStorage.removeItem("siteops_pending_access_request");
      setMessage("Your email is verified and the request is now awaiting administrator review.");
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }

  async function leaveVerification() {
    await authApi.logout().catch(() => {});
    navigate("login");
  }

  async function forgot(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const form = new FormData(event.currentTarget);
      const result = await authApi.requestReset(form.get("email"));
      setMessage(result.message);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }

  async function resetPassword(event) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const password = form.get("password");
    if (password !== form.get("confirm_password")) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      await authApi.updatePassword(password);
      await authApi.completeActivation();
      await authApi.logout();
      setRecoveryReady(false);
      window.history.replaceState({}, "", window.location.pathname);
      setMessage("Password updated. Sign in with your new password.");
      setView("login");
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    await authApi.logout().catch(() => {});
    setUser(null);
    navigate("login");
  }

  if (loading && !user && view !== "verify-access") return <main className="grid min-h-screen place-items-center bg-slate-950 text-sm font-bold text-blue-100">Opening secure workspace…</main>;
  if (!user && view === "request-access") return <AccessRequestPage onSubmit={requestAccess} onBack={() => navigate("login")} error={error} message={message} loading={loading}/>;
  if (!user && view === "verify-access") return <VerifyAccessPage onVerify={verifyAccess} onBack={leaveVerification} error={error} message={message} loading={loading} ready={verificationReady}/>;
  if (!user && view === "forgot-password") return <ForgotPasswordPage onSubmit={forgot} onBack={() => navigate("login")} error={error} message={message} loading={loading}/>;
  if (!user && view === "reset-password" && recoveryReady) return <ResetPasswordPage onSubmit={resetPassword} error={error} loading={loading}/>;
  if (!user) return <LoginPage onSubmit={login} onForgot={() => navigate("forgot-password")} onRequest={() => navigate("request-access")} error={error} message={message} loading={loading}/>;
  return <Dashboard initialUser={user} onLogout={logout}/>;
}

createRoot(document.getElementById("root")).render(<App/>);