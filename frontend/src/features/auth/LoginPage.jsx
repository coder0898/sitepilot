export function LoginPage({ onSubmit, error }) {
  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="login-hero">
          <div className="logo-mark">45</div>
          <p>Interior fit-out management</p>
          <h1>SiteOps command center</h1>
          <span>Daily task calendars, vendor coordination, supervisor proof, and PM approvals.</span>
        </div>
        <form onSubmit={onSubmit} className="login-form">
          <label>Email<input name="email"  /></label>
          <label>Password<input name="password" type="password"  /></label>
          {error && <p className="error">{error}</p>}
          <button>Login to workspace</button>
          <a href="#forgot" onClick={(e) => { e.preventDefault(); alert("Forgot password is inside Security after login for local MVP."); }}>Forgot password?</a>
        </form>
      </section>
    </main>
  );
}

