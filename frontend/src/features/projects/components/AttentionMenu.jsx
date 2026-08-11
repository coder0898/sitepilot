import { Bell, CircleAlert, Clock3, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const severityStyle = {
  critical: { wrap: "bg-rose-50 text-rose-700", Icon: CircleAlert },
  warning: { wrap: "bg-amber-50 text-amber-700", Icon: Clock3 },
  decision: { wrap: "bg-blue-50 text-blue-700", Icon: ShieldCheck },
};

function AttentionItem({ item, onOpen }) {
  const { wrap, Icon } = severityStyle[item.severity] || severityStyle.warning;
  return <button
    type="button"
    onClick={() => onOpen(item)}
    className="grid w-full grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2 rounded-lg px-1.5 py-1.5 text-left transition hover:bg-slate-100"
  >
    <span className={`grid size-[22px] place-items-center rounded-md ${wrap}`}><Icon size={12} aria-hidden="true"/></span>
    <span className="min-w-0">
      <span className="block truncate text-xs font-bold text-slate-950">{item.title}</span>
      <span className="block truncate text-[11px] text-slate-500">{item.subtitle}</span>
    </span>
    {item.due_label && <span className="shrink-0 pt-0.5 font-mono text-[10px] text-slate-400">{item.due_label}</span>}
  </button>;
}

export function AttentionMenu({ items, onOpen }) {
  const [open, setOpen] = useState(false);
  const holder = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onDocument(event) {
      if (!holder.current?.contains(event.target)) setOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocument);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocument);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // The attention read model has not shipped yet, or genuinely returned
  // nothing. Either way there is no counter worth showing.
  if (!items?.length) return null;

  const groups = [...new Set(items.map(item => item.group))];

  return <div className="relative" ref={holder}>
    <button
      type="button"
      onClick={() => setOpen(value => !value)}
      aria-expanded={open}
      aria-haspopup="true"
      className={`inline-flex min-h-10 items-center gap-2 rounded-xl border px-3 text-xs font-bold transition ${open ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:text-slate-950"}`}
    >
      <Bell size={15} aria-hidden="true"/>
      <span className="hidden sm:inline">Needs attention</span>
      <span className="rounded-full bg-rose-600 px-1.5 font-mono text-[10px] text-white">{items.length}</span>
    </button>

    {open && <div
      role="menu"
      className="absolute right-0 top-[calc(100%+.35rem)] z-40 max-h-80 w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_24px_60px_rgba(15,23,42,.18)]"
    >
      {groups.map(group => <div key={group}>
        <p className="flex items-center gap-2 px-1.5 pb-1 pt-2 font-mono text-[10px] uppercase tracking-[.12em] text-slate-400">
          {group}<span className="h-px flex-1 bg-slate-100"/>
        </p>
        {items.filter(item => item.group === group).map(item => <AttentionItem
          key={item.id}
          item={item}
          onOpen={selected => { setOpen(false); onOpen(selected); }}
        />)}
      </div>)}
    </div>}
  </div>;
}
