import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { authApi } from "./api/authApi";
import { cachedUser, clearSession, saveSession } from "./api/client";
import { LoginPage } from "./features/auth/LoginPage";
import { Dashboard } from "./features/dashboard/Dashboard";
import "./styles.css";

function App() {
  const [user, setUser] = useState(cachedUser());
  const [loginError, setLoginError] = useState("");

  async function login(e) {
    e.preventDefault();
    setLoginError("");
    const form = new FormData(e.currentTarget);
    try {
      const session = await authApi.login(form.get("email"), form.get("password"));
      saveSession(session);
      setUser(session.user);
    } catch (err) {
      setLoginError(err.message);
    }
  }

  function logout() {
    clearSession();
    setUser(null);
  }

  if (!user) return <LoginPage onSubmit={login} error={loginError} />;
  return <Dashboard initialUser={user} onLogout={logout} />;
}

createRoot(document.getElementById("root")).render(<App />);
