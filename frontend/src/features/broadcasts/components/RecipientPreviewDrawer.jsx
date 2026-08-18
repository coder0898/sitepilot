import { AlertTriangle, Building2, LayoutGrid, Mail, MessageCircle, Phone, X } from "lucide-react";
import { useEffect } from "react";
import { Pill } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { StatusChip } from "./StatusChip";

const CHANNEL_META = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle, tone: "text-emerald-600 bg-emerald-50" },
  email: { label: "Email", icon: Mail, tone: "text-blue-600 bg-blue-50" },
  in_app: { label: "In-app", icon: LayoutGrid, tone: "text-violet-600 bg-violet-50" },
};

function ChannelBadges({ channels = [] }) {
  if (!channels.length) return <span className="flex items-center gap-1 text-xs font-bold text-amber-700"><AlertTriangle size={13} /> No contact channel</span>;
  return <div className="flex flex-wrap gap-1.5">{channels.map(channel => {
    const meta = CHANNEL_META[channel] || { label: channel, icon: MessageCircle, tone: "text-slate-500 bg-slate-100" };
    const Icon = meta.icon;
    return <span key={channel} className={cn("flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold", meta.tone)}><Icon size={11} /> {meta.label}</span>;
  })}</div>;
}

// Right-side overlay drawer, same fixed-position chrome as Execution's
// TaskDetailDrawer / Vendor Hub's VendorDetailPanel: backdrop behind it,
// page locked from scrolling while open, bounded height from `inset-y-0`
// with only the recipient list scrolling internally.
export function RecipientPreviewDrawer({ title, subtitle, recipients = [], readOnly = false, excludedKeys, onToggleExclude, deliverySummary, onClose }) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  const includedCount = readOnly ? recipients.length : recipients.filter(item => !excludedKeys?.has(item.key)).length;
  const missingContactCount = recipients.filter(item => !(item.channels || []).length).length;

  return <>
    <div className="fixed inset-0 z-40 bg-slate-950/40" onClick={onClose} aria-hidden="true" />
    <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[90vw] flex-col bg-white shadow-[-16px_0_50px_rgba(15,23,42,.18)] sm:w-[560px]" aria-label="Recipient preview">
      <section className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 p-4 sm:p-5">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-black tracking-tight text-slate-950">{title}</h2>
          <p className="mt-0.5 text-xs font-bold text-slate-500">{subtitle}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Pill tone="blue">{includedCount} recipient{includedCount === 1 ? "" : "s"}</Pill>
            {missingContactCount > 0 && <Pill tone="orange"><AlertTriangle size={11} className="mr-1 inline" />{missingContactCount} missing contact</Pill>}
          </div>
        </div>
        <button type="button" aria-label="Close recipient preview" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><X size={18} /></button>
      </section>

      {deliverySummary && <div className="flex shrink-0 flex-wrap gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3 sm:px-5">
        <Pill tone="green">{deliverySummary.sent} sent</Pill>
        <Pill tone="gray">{deliverySummary.pending} pending</Pill>
        <Pill tone="orange">{deliverySummary.skipped_no_contact} skipped</Pill>
      </div>}

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain bg-slate-50 p-4 sm:p-5">
        {recipients.length === 0
          ? <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">No recipients resolved for the current selection.</p>
          : <div className="grid gap-2">{recipients.map(recipient => {
              const excluded = !readOnly && excludedKeys?.has(recipient.key);
              return <article key={recipient.key || recipient.id} className={cn("grid gap-2 rounded-2xl border bg-white p-3.5 transition", excluded ? "border-slate-200 opacity-50" : "border-slate-200")}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <strong className="truncate text-sm font-black text-slate-950">{recipient.name}</strong>
                      <Pill tone="gray">{recipient.role_label}</Pill>
                    </div>
                    {recipient.company_name && <p className="mt-0.5 flex items-center gap-1 text-xs font-semibold text-slate-500"><Building2 size={12} /> {recipient.company_name}</p>}
                  </div>
                  {readOnly
                    ? <StatusChip status={recipient.delivery_status} />
                    : <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs font-bold text-slate-500">
                        Include
                        <input type="checkbox" checked={!excluded} onChange={() => onToggleExclude(recipient.key)} className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-600" />
                      </label>}
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-600">
                  {recipient.phone && <span className="flex items-center gap-1"><Phone size={12} /> {recipient.phone}</span>}
                  {recipient.email && <span className="flex items-center gap-1"><Mail size={12} /> {recipient.email}</span>}
                </div>
                <ChannelBadges channels={recipient.channels} />
              </article>;
            })}</div>}
      </div>
    </aside>
  </>;
}
