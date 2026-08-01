import { ArrowLeft, ArrowRight, BadgeCheck, Building2, CheckCircle2, LoaderCircle, MailCheck, ShieldCheck, UserRoundCheck } from "lucide-react";
import { AuthShell, Notice, SubmitButton, TextField } from "./LoginPage";

const roles = [
  ["admin", "Admin"],
  ["project_manager", "Project Manager"],
  ["supervisor", "Supervisor"],
  ["internal_employee", "Internal Employee"],
];

function SelectField({ label, children, ...props }) {
  return <label className="grid gap-2 text-sm font-black text-slate-700"><span>{label}</span><select className="min-h-13 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-950 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100" {...props}>{children}</select></label>;
}

function TextAreaField({ label, hint, ...props }) {
  return <label className="grid gap-2 text-sm font-black text-slate-700"><span>{label}</span><textarea className="min-h-28 w-full resize-y rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold leading-6 text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-100" {...props}/>{hint && <small className="font-medium leading-5 text-slate-400">{hint}</small>}</label>;
}

export function AccessRequestPage({ onSubmit, onBack, error, message, loading }) {
  if (message) return <AuthShell eyebrow="Request received" title="Verify your work email" subtitle="Your profile is not active yet. Email verification must be completed before an administrator can review it.">
    <div className="mt-8 rounded-[24px] border border-emerald-200 bg-emerald-50 p-5">
      <span className="grid size-12 place-items-center rounded-2xl bg-emerald-600 text-white"><MailCheck size={23}/></span>
      <h3 className="mt-4 text-lg font-black text-emerald-950">Verification link sent</h3>
      <p className="mt-2 text-sm leading-6 text-emerald-800">{message}</p>
    </div>
    <button type="button" onClick={onBack} className="mt-5 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-black text-slate-700 hover:bg-slate-50"><ArrowLeft size={17}/>Return to sign in</button>
  </AuthShell>;

  return <AuthShell eyebrow="Controlled onboarding" title="Request SiteOps access" subtitle="Provide your company identity. No password is collected until your request is verified and approved.">
    <button type="button" onClick={onBack} className="mt-6 inline-flex items-center gap-2 text-sm font-black text-slate-500 hover:text-slate-900"><ArrowLeft size={17}/>Back to sign in</button>
    <form onSubmit={onSubmit} className="mt-6 grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField icon={<UserRoundCheck size={18}/>} label="Full name" name="name" autoComplete="name" placeholder="Your full name" required/>
        <TextField icon={<MailCheck size={18}/>} label="Work email" name="email" type="email" autoComplete="email" placeholder="name@company.com" required/>
        <TextField icon={<BadgeCheck size={18}/>} label="Employee code" name="employee_code" placeholder="EMP-001" required/>
        <TextField icon={<Building2 size={18}/>} label="Mobile number" name="phone" type="tel" placeholder="+919876543210" required/>
        <TextField icon={<ShieldCheck size={18}/>} label="Designation" name="designation" placeholder="Site Engineer" required/>
        <TextField icon={<Building2 size={18}/>} label="Department" name="department" placeholder="Projects"/>
      </div>
      <SelectField label="Requested role" name="requested_role" required>
        <option value="">Select role</option>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </SelectField>
      <TextField icon={<Building2 size={18}/>} label="Project reference (optional)" name="project_reference" placeholder="Project name or internal reference"/>
      <TextAreaField label="Why do you need access?" name="justification" minLength={10} placeholder="Describe your responsibility and required access." hint="This helps the reviewer validate the request. Project assignment remains a separate approval step." required/>
      <Notice error={error}/>
      <SubmitButton loading={loading}>Send verification link<ArrowRight size={18}/></SubmitButton>
      <p className="text-center text-xs leading-5 text-slate-400">Submitting a request does not create portal access. An Admin or Super Admin must approve it.</p>
    </form>
  </AuthShell>;
}

export function VerifyAccessPage({ onVerify, onBack, error, message, loading, ready }) {
  return <AuthShell eyebrow="Email ownership" title={message ? "Email verified" : "Verify access request"} subtitle={message || "Confirm the email link to place your request in the administrator approval queue."}>
    <div className="mt-8 rounded-[24px] border border-blue-100 bg-blue-50 p-5">
      <span className="grid size-12 place-items-center rounded-2xl bg-blue-700 text-white">{message ? <CheckCircle2 size={24}/> : <MailCheck size={24}/>}</span>
      <h3 className="mt-4 text-lg font-black text-slate-950">{message ? "Awaiting administrator review" : "One secure confirmation"}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{message ? "You cannot sign in until approval. When approved, you will receive a separate password-setup email." : "Use the button below after opening the link sent to your work email."}</p>
    </div>
    <div className="mt-5 grid gap-3">
      {!message && <button type="button" onClick={onVerify} disabled={loading || !ready} className="inline-flex min-h-13 items-center justify-center gap-2 rounded-2xl bg-blue-700 px-5 text-sm font-black text-white shadow-[0_14px_30px_rgba(29,78,216,.22)] hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 disabled:shadow-none">{loading ? <LoaderCircle className="animate-spin" size={18}/> : <><ShieldCheck size={18}/>{ready ? "Verify and submit for review" : "Open a fresh verification email"}</>}</button>}
      <Notice error={error}/>
      <button type="button" onClick={onBack} className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-black text-slate-700 hover:bg-slate-50"><ArrowLeft size={17}/>{error ? "Sign out and try again" : "Return to sign in"}</button>
    </div>
  </AuthShell>;
}