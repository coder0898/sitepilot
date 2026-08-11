import { Activity } from "lucide-react";
import { EmptyState } from "../../../components/ui";

const actionLabel = value => value.toLowerCase().replaceAll("_", " ").replace(/(^|\s)\S/g, match => match.toUpperCase());

export function ProjectActivityPane({ activity }) {
  if (!activity.length) {
    return <EmptyState icon={<Activity size={20}/>} title="No recorded activity" description="Project changes will appear here automatically."/>;
  }
  return <ol className="grid gap-0">
    {activity.map((event, index) => <li key={event.id} className="relative grid grid-cols-[36px_minmax(0,1fr)] gap-3 pb-5">
      <div className="relative grid size-9 place-items-center rounded-full border border-slate-200 bg-white text-blue-700 shadow-sm">
        <Activity size={15} aria-hidden="true"/>
        {index < activity.length - 1 && <span className="absolute left-1/2 top-9 h-[calc(100%+4px)] w-px -translate-x-1/2 bg-slate-200"/>}
      </div>
      <article className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <strong className="text-sm text-slate-950">{actionLabel(event.action)}</strong>
          <time className="font-mono text-[11px] text-slate-400">{new Date(event.occurred_at).toLocaleString("en-GB")}</time>
        </div>
        <p className="mt-1 text-sm leading-6 text-slate-600">{event.reason}</p>
        <span className="mt-2 block text-xs font-bold text-slate-400">{event.actor_name}</span>
      </article>
    </li>)}
  </ol>;
}
