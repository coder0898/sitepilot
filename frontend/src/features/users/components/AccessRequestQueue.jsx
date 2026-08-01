import { useEffect, useMemo, useState } from "react";
import { BadgeCheck, Check, Clock3, FileClock, History, MailCheck, Plus, RefreshCw, Send, ShieldCheck, UserCheck, X } from "lucide-react";
import { accessRequestsApi } from "../../../api/accessRequestsApi";

import { Button, Field, Input, Modal, Pill, Select, Textarea } from "../../../components/ui";
import { roles } from "../../../utils/constants";

const roleOptions = [
  ["admin", "Admin"],
  ["project_manager", "Project Manager"],
  ["supervisor", "Supervisor"],
  ["internal_employee", "Internal Employee"],
];

const statusMeta = {
  pending_email_verification: ["Email verification", "orange"],
  pending_approval: ["Awaiting review", "blue"],
  approved: ["Approved", "green"],
  rejected: ["Rejected", "red"],
  expired: ["Expired", "gray"],
  cancelled: ["Cancelled", "gray"],
};

function RequestStatus({ status }) {
  const [label, tone] = statusMeta[status] || [status, "gray"];
  return <Pill tone={tone}>{label}</Pill>;
}

function RequestForm({ onClose, onCreated, action }) {
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const result = await action(
      () => accessRequestsApi.createOnBehalf(form),
      "Request recorded. Verification email sent; Super Admin approval follows email confirmation.",
      { refresh: false },
    );
    setBusy(false);
    if (result?.ok) { await onCreated(); onClose(); }
  }
  return <Modal title="Submit employee access request" subtitle="Admin-submitted requests require independent Super Admin approval. The employee must verify their work email." onClose={onClose} className="sm:max-w-3xl">
    <form onSubmit={submit} className="grid gap-5">
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name"><Input name="name" required/></Field>
        <Field label="Work email"><Input name="email" type="email" required/></Field>
        <Field label="Mobile number" hint="Use international format, for example +919876543210."><Input name="phone" type="tel" placeholder="+919876543210" required/></Field>
        <Field label="Employee code"><Input name="employee_code" required/></Field>
        <Field label="Designation"><Input name="designation" required/></Field>
        <Field label="Department"><Input name="department"/></Field>
        <Field label="Requested role">
          <Select name="requested_role" required><option value="">Select role</option>{roleOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select>
        </Field>
        <Field label="Project reference" hint="Context only; this does not assign the employee to a project."><Input name="project_reference"/></Field>
      </section>
      <Field label="Access justification"><Textarea name="justification" minLength={10} required/></Field>
      <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}><Send size={17}/>Send verification request</Button></div>
    </form>
  </Modal>;
}

function ReviewModal({ item, user, events, onClose, onSaved, action }) {
  const [busy, setBusy] = useState(false);
  async function submit(source, decision) {
    source.preventDefault?.();
    const form = source.currentTarget?.tagName === "FORM" ? source.currentTarget : source;
    const payload = Object.fromEntries(new FormData(form));
    setBusy(true);
    const operation = decision === "approve"
      ? () => accessRequestsApi.approve(item.id, payload)
      : () => accessRequestsApi.reject(item.id, { reason: payload.reason });
    const result = await action(
      operation,
      decision === "approve" ? "Access approved and password setup requested" : "Access request rejected",
      decision === "approve" ? {} : { refresh: false },
    );
    setBusy(false);
    if (result?.ok) { await onSaved(); onClose(); }
  }

  async function resendVerification() {
    setBusy(true);
    await action(() => accessRequestsApi.resendVerification(item.id), "Verification email sent again", { refresh: false });
    setBusy(false);
  }

  async function resendActivation() {
    setBusy(true);
    await action(() => accessRequestsApi.resendActivation(item.id), "Password setup email sent again", { refresh: false });
    setBusy(false);
  }

  return <Modal title="Review access request" subtitle="Verify employment and the minimum role needed before making a decision." onClose={onClose} className="sm:max-w-3xl">
    <div className="grid gap-5">
      <section className="rounded-[22px] bg-[#071a33] p-5 text-white">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-[.16em] text-blue-300">Requested identity</p><h3 className="mt-2 text-2xl font-black">{item.name}</h3><p className="mt-1 text-sm text-blue-100/70">{item.email}</p></div><RequestStatus status={item.status}/></div>
        <div className="mt-5 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">{[["Role", roles[item.requested_role] || item.requested_role],["Employee", item.employee_code],["Designation", item.designation],["Submitted by", item.submitted_by_name],["Reviewer", item.reviewer_label]].map(([label,value]) => <div key={label} className="rounded-2xl bg-white/8 p-3"><span className="block text-[10px] font-black uppercase tracking-[.12em] text-blue-200/60">{label}</span><strong className="mt-1 block break-words">{value || "Not provided"}</strong></div>)}</div>
      </section>

      <section className="grid gap-3 rounded-[20px] border border-slate-200 bg-slate-50 p-4 text-sm sm:grid-cols-2">
        <div><span className="font-black text-slate-500">Project context</span><p className="mt-1 leading-6 text-slate-800">{item.project_reference || "No project reference"}</p></div>
        <div><span className="font-black text-slate-500">Justification</span><p className="mt-1 leading-6 text-slate-800">{item.justification}</p></div>
      </section>

      {item.can_review ? <form onSubmit={event => submit(event, "approve")} className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Approved role"><Select name="role" defaultValue={item.requested_role}>{roleOptions.filter(([value]) => user.role === "super_admin" || value !== "admin").map(([value,label]) => <option key={value} value={value}>{label}</option>)}</Select></Field>
          <Field label="Employee code"><Input name="employee_code" defaultValue={item.employee_code || ""} required/></Field>
          <Field label="Designation"><Input name="designation" defaultValue={item.designation || ""} required/></Field>
          <Field label="Department"><Input name="department" defaultValue={item.department || ""}/></Field>
        </div>
        <Field label="Review note" hint="Required when rejecting; recommended for an auditable approval."><Textarea name="reason" placeholder="Employment verified and least-privilege role confirmed."/></Field>
        <div className="grid gap-2 sm:grid-cols-2"><Button type="button" variant="danger" loading={busy} onClick={event => submit(event.currentTarget.form, "reject")}><X size={17}/>Reject request</Button><Button type="submit" loading={busy}><Check size={17}/>Approve access</Button></div>
      </form> : <div className="flex items-start gap-3 rounded-[18px] border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900"><ShieldCheck className="mt-0.5 shrink-0" size={20}/><p>{item.status === "pending_email_verification" ? "The employee must verify the work email before this request can be reviewed." : item.submitted_by && user.role === "admin" ? "Admin-submitted requests require Super Admin review. Self-approval is blocked." : "This request is read-only for your role or has already been decided."}</p></div>}

      {item.status === "pending_email_verification" && <div className="flex flex-col gap-3 rounded-[18px] border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between"><p className="text-sm leading-6 text-amber-900">Approval unlocks only after the employee verifies the work email.</p><Button variant="secondary" loading={busy} onClick={resendVerification}><Send size={17}/>Resend verification</Button></div>}
      {item.status === "approved" && <div className="flex justify-end"><Button variant="secondary" loading={busy} onClick={resendActivation}><Send size={17}/>Resend password setup</Button></div>}

      <section className="border-t border-slate-100 pt-4"><div className="flex items-center gap-2 text-xs font-black uppercase tracking-[.14em] text-slate-500"><History size={16}/>Audit trail</div><div className="mt-3 grid gap-2">{events.length ? events.map(event => <div key={event.id} className="rounded-2xl bg-slate-50 px-4 py-3"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm text-slate-900">{event.event_type.replaceAll("_", " ")}</strong><span className="text-xs text-slate-400">{new Date(event.created_at).toLocaleString()}</span></div><p className="mt-1 text-xs leading-5 text-slate-500">{event.reason}</p></div>) : <p className="text-sm text-slate-400">No audit events available.</p>}</div></section>
    </div>
  </Modal>;
}

export function AccessRequestQueue({ user, action }) {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("open");
  const [selected, setSelected] = useState(null);
  const [events, setEvents] = useState([]);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try { setItems(await accessRequestsApi.list()); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function open(item) {
    setSelected(item);
    try { setEvents(await accessRequestsApi.events(item.id)); }
    catch { setEvents([]); }
  }

  const shown = useMemo(() => items.filter(item => filter === "all" || (filter === "open" ? item.status.startsWith("pending_") : item.status === filter)), [items, filter]);
  const pending = items.filter(item => item.status === "pending_approval" && item.can_review).length;

  return <section className="overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,.06)]">
    <header className="flex flex-col gap-4 border-b border-slate-200 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
      <div><div className="flex items-center gap-2"><span className="grid size-10 place-items-center rounded-2xl bg-violet-50 text-violet-700"><FileClock size={19}/></span><Pill tone={pending ? "orange" : "gray"}>{pending} ready for review</Pill></div><h2 className="mt-4 text-2xl font-black tracking-[-.035em] text-slate-950">Access request inbox</h2><p className="mt-1 text-sm leading-6 text-slate-500">Email verification, independent approval, activation, and audit history in one queue.</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={load} loading={loading}><RefreshCw size={17}/>Refresh</Button>{user.role === "admin" && <Button onClick={() => setCreating(true)}><Plus size={17}/>Submit for employee</Button>}</div>
    </header>
    <div className="flex gap-2 overflow-x-auto border-b border-slate-100 p-4 sm:px-6">{[["open","Open"],["approved","Approved"],["rejected","Rejected"],["all","All"]].map(([value,label]) => <button key={value} type="button" onClick={() => setFilter(value)} className={`min-h-10 shrink-0 rounded-xl px-4 text-sm font-black transition ${filter === value ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{label}</button>)}</div>
    {loading ? <div className="grid place-items-center py-14 text-sm font-bold text-slate-400">Loading access requests…</div> : shown.length ? <div className="divide-y divide-slate-100">{shown.map(item => <button key={item.id} type="button" onClick={() => open(item)} className="grid w-full gap-3 p-4 text-left transition hover:bg-blue-50/50 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-6">
      <div className="flex min-w-0 items-start gap-3"><span className={`grid size-11 shrink-0 place-items-center rounded-2xl ${item.status === "approved" ? "bg-emerald-50 text-emerald-700" : item.status === "rejected" ? "bg-rose-50 text-rose-700" : "bg-blue-50 text-blue-700"}`}>{item.email_verified_at ? <UserCheck size={20}/> : <MailCheck size={20}/>}</span><span className="min-w-0"><span className="flex flex-wrap items-center gap-2"><strong className="truncate text-sm text-slate-950">{item.name}</strong><RequestStatus status={item.status}/>{item.can_review && <Pill tone="orange">Action needed</Pill>}</span><span className="mt-1 block truncate text-xs text-slate-500">{item.email}</span><span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs font-bold text-slate-600"><span>{roles[item.requested_role] || item.requested_role}</span><span>{item.designation}</span><span>{item.submitted_by_name}</span></span></span></div>
      <span className="flex items-center gap-2 text-xs font-bold text-slate-400 sm:justify-end"><Clock3 size={15}/>{new Date(item.created_at).toLocaleDateString()}</span>
    </button>)}</div> : <div className="grid place-items-center px-5 py-14 text-center"><span className="grid size-14 place-items-center rounded-[20px] bg-emerald-50 text-emerald-700"><BadgeCheck size={25}/></span><h3 className="mt-4 font-black text-slate-900">Queue is clear</h3><p className="mt-1 text-sm text-slate-500">No access requests match this view.</p></div>}
    {creating && <RequestForm onClose={() => setCreating(false)} onCreated={load} action={action}/>}
    {selected && <ReviewModal item={selected} user={user} events={events} onClose={() => setSelected(null)} onSaved={load} action={action}/>}
  </section>;
}