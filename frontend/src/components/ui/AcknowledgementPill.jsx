import { Pill } from "./Pill";

// Telegram T2: whether the person (or vendor) pressed Acknowledge on their
// assignment message. A receipt only - it grants nothing.
export function AcknowledgementPill({ acknowledgedAt }) {
  if (!acknowledgedAt) return <Pill tone="gray">Not acknowledged</Pill>;
  const when = new Date(acknowledgedAt).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
  return <span title={`Acknowledged on Telegram, ${when}`}><Pill tone="green">Acknowledged</Pill></span>;
}
