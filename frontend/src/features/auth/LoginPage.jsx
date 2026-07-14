export function LoginPage({ onSubmit, error }) {
  return (
    <main className="login-shell grid min-h-screen place-items-center bg-[radial-gradient(circle_at_top_left,#dbeafe,transparent_34%),linear-gradient(135deg,#f8fbff_0%,#e8f1fb_100%)] p-6 max-[520px]:block max-[520px]:p-0">
      <section className="login-card grid w-full max-w-[1080px] grid-cols-[0.9fr_1.1fr] overflow-hidden rounded-[28px] bg-white shadow-[0_30px_90px_rgba(15,45,86,0.18)] max-[920px]:grid-cols-1 max-[520px]:min-h-screen max-[520px]:rounded-none">
        <div className="login-hero bg-gradient-to-br from-[#06265d] to-[#1368f0] p-11 text-white max-[920px]:p-8 max-[520px]:p-6 [&>p]:mb-2 [&>p]:mt-5 [&>p]:text-xs [&>p]:font-black [&>p]:uppercase [&>p]:tracking-[0.18em] [&>p]:text-blue-200 [&>h1]:mb-5 [&>h1]:text-[clamp(42px,7vw,76px)] [&>h1]:font-black [&>h1]:leading-[0.93] [&>h1]:tracking-[-0.07em] [&>span]:text-lg [&>span]:leading-relaxed [&>span]:text-blue-100">
          <div className="logo-mark grid size-[150px] h-[50px] shrink-0 place-items-center rounded-[18px] bg-blue-700 text-[21px] font-black text-white shadow-[0_16px_30px_rgba(11,91,211,0.25)]">Workved</div>
          <h1 className="text-xl">INTERIOR PROJECT COMMAND CENTER</h1>
          <p>From site chaos</p>
          <p>to complete control.</p>
          <span>Organise tasks, coordinate teams, track site progress, verify completion, and keep every project moving forward.</span>
        </div>
        <form onSubmit={onSubmit} className="login-form grid content-center gap-5 p-11 max-[520px]:p-6 [&_label]:grid [&_label]:gap-2 [&_label]:font-extrabold [&_input]:min-h-12 [&_input]:w-full [&_input]:rounded-2xl [&_input]:border [&_input]:border-blue-200 [&_input]:bg-white [&_input]:px-4 [&_input]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_input]:ring-4 focus-within:[&_input]:ring-blue-600/10 [&_button]:min-h-12 [&_button]:rounded-2xl [&_button]:bg-blue-700 [&_button]:px-5 [&_button]:font-black [&_button]:text-white [&_a]:font-black [&_a]:text-blue-700">
          <label>Email<input name="email"  /></label>
          <label>Password<input name="password" type="password"  /></label>
          {error && <p className="error rounded-xl bg-rose-100 px-4 py-3 font-bold text-rose-800">{error}</p>}
          <button>Login to workspace</button>
          <a href="#forgot" onClick={(e) => { e.preventDefault(); alert("Forgot password is inside Security after login for local MVP."); }}>Forgot password?</a>
        </form>
      </section>
    </main>
  );
}

