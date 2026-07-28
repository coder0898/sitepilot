import { ArrowLeft, ArrowRight, CheckCircle2, KeyRound, LoaderCircle, LockKeyhole, Mail, ShieldCheck } from "lucide-react";

function BrandPanel() {
  return <aside className="relative overflow-hidden bg-[#071a33] p-7 text-white sm:p-10 lg:p-12">
    <div className="absolute -right-28 -top-28 size-80 rounded-full border-[64px] border-blue-500/10"/>
    <div className="absolute -bottom-24 -left-20 size-64 rounded-full border-[44px] border-cyan-300/5"/>
    <div className="relative flex h-full min-h-64 flex-col">
      <div className="flex items-center gap-3"><span className="grid size-11 place-items-center rounded-2xl bg-blue-600 text-sm font-black shadow-[0_14px_30px_rgba(37,99,235,.35)]">45</span><span><strong className="block text-lg font-black tracking-[-.02em]">Workved SiteOps</strong><small className="text-xs font-semibold text-blue-200/70">Execution intelligence</small></span></div>
      <div className="my-auto py-10"><p className="text-xs font-black uppercase tracking-[.22em] text-blue-300">Secure project command</p><h1 className="mt-4 max-w-md text-4xl font-black leading-[.98] tracking-[-.055em] sm:text-5xl">Every site decision, under control.</h1><p className="mt-5 max-w-md text-sm leading-7 text-blue-100/70">Coordinate teams, verify execution, and protect operational accountability through one trusted workspace.</p></div>
      <div className="flex items-center gap-2 text-xs font-bold text-blue-100/60"><ShieldCheck size={16}/>Authentication protected by Supabase</div>
    </div>
  </aside>;
}

export function AuthShell({ eyebrow, title, subtitle, children }) {
  return <main className="min-h-screen bg-[radial-gradient(circle_at_10%_10%,#dbeafe_0,transparent_32%),linear-gradient(135deg,#f8fafc,#eaf2fb)] p-0 sm:grid sm:place-items-center sm:p-6">
    <section className="grid min-h-screen w-full overflow-hidden bg-white shadow-[0_32px_100px_rgba(15,23,42,.18)] sm:min-h-0 sm:max-w-6xl sm:grid-cols-[.9fr_1.1fr] sm:rounded-[32px]">
      <BrandPanel/>
      <div className="grid content-center px-5 py-9 sm:px-10 lg:px-16 lg:py-14"><div className="mx-auto w-full max-w-md"><p className="text-xs font-black uppercase tracking-[.2em] text-blue-700">{eyebrow}</p><h2 className="mt-2 text-3xl font-black tracking-[-.04em] text-slate-950 sm:text-4xl">{title}</h2><p className="mt-3 text-sm leading-6 text-slate-500">{subtitle}</p>{children}</div></div>
    </section>
  </main>;
}

export function Notice({ error, message }) {
  if (error) return <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-800">{error}</div>;
  if (message) return <div className="flex items-start gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-800"><CheckCircle2 className="mt-0.5 shrink-0" size={17}/>{message}</div>;
  return null;
}

export function TextField({ icon, label, ...props }) {
  return <label className="grid gap-2 text-sm font-black text-slate-700"><span>{label}</span><span className="relative"><span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">{icon}</span><input className="min-h-13 w-full rounded-2xl border border-slate-200 bg-white pl-11 pr-4 text-sm font-semibold text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-100" {...props}/></span></label>;
}

export function SubmitButton({ loading, children }) {
  return <button type="submit" disabled={loading} className="inline-flex min-h-13 w-full items-center justify-center gap-2 rounded-2xl bg-blue-700 px-5 text-sm font-black text-white shadow-[0_14px_30px_rgba(29,78,216,.22)] transition hover:bg-blue-800 disabled:cursor-wait disabled:opacity-60">{loading ? <LoaderCircle className="animate-spin" size={18}/> : children}</button>;
}

export function LoginPage({ onSubmit, onForgot, onRequest, error, message, loading }) {
  return <AuthShell eyebrow="Welcome back" title="Sign in to SiteOps" subtitle="Use the company account issued by your administrator."><form onSubmit={onSubmit} className="mt-8 grid gap-5"><TextField icon={<Mail size={18}/>} label="Work email" name="email" type="email" autoComplete="email" placeholder="name@company.com" required/><TextField icon={<LockKeyhole size={18}/>} label="Password" name="password" type="password" autoComplete="current-password" placeholder="Enter your password" required/><div className="-mt-2 flex justify-end"><button type="button" onClick={onForgot} className="text-sm font-black text-blue-700 transition hover:text-blue-900">Forgot password?</button></div><Notice error={error} message={message}/><SubmitButton loading={loading}>Open workspace<ArrowRight size={18}/></SubmitButton><div className="flex items-center gap-3"><span className="h-px flex-1 bg-slate-200"/><span className="text-[11px] font-black uppercase tracking-[.14em] text-slate-400">New to SiteOps?</span><span className="h-px flex-1 bg-slate-200"/></div><button type="button" onClick={onRequest} className="min-h-12 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-black text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800">Request workspace access</button></form></AuthShell>;
}

export function ForgotPasswordPage({ onSubmit, onBack, error, message, loading }) {
  return <AuthShell eyebrow="Account recovery" title="Reset your password" subtitle="Enter your registered email. Supabase will send a secure, time-limited recovery link."><button type="button" onClick={onBack} className="mt-7 inline-flex items-center gap-2 text-sm font-black text-slate-500 hover:text-slate-900"><ArrowLeft size={17}/>Back to sign in</button><form onSubmit={onSubmit} className="mt-6 grid gap-5"><TextField icon={<Mail size={18}/>} label="Work email" name="email" type="email" autoComplete="email" placeholder="name@company.com" required/><Notice error={error} message={message}/><SubmitButton loading={loading}>Send recovery email<Mail size={18}/></SubmitButton><p className="text-center text-xs leading-5 text-slate-400">For security, the response is the same whether or not an account exists.</p></form></AuthShell>;
}

export function ResetPasswordPage({ onSubmit, error, loading }) {
  return <AuthShell eyebrow="Secure recovery" title="Choose a new password" subtitle="This recovery session came from your Supabase email link. Use at least eight characters."><form onSubmit={onSubmit} className="mt-8 grid gap-5"><TextField icon={<KeyRound size={18}/>} label="New password" name="password" type="password" autoComplete="new-password" minLength={8} placeholder="Minimum 8 characters" required/><TextField icon={<LockKeyhole size={18}/>} label="Confirm new password" name="confirm_password" type="password" autoComplete="new-password" minLength={8} placeholder="Repeat your password" required/><Notice error={error}/><SubmitButton loading={loading}>Update password<ShieldCheck size={18}/></SubmitButton></form></AuthShell>;
}
