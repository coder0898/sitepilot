// Retired phases: offered only on a task that already uses one.
export const LEGACY_PHASES = ["Pre-Activation"];

export const APPROVED_PHASES = [
  "Mobilisation","Coordination","Survey","Planning","Design & Planning","Shop Drawings","Procurement","Off-Site Production","Dismantling","Civil","Partitions","MEP First Fix","Floor Base","Ceiling","Carpentry","Doors & Glass","MEP Second Fix","Fire Second Fix","Flooring","Painting","Furniture","IT & ELV","Security","Testing","Inspection","Snagging","Rectification","Cleaning","Documentation","Handover","Demobilisation"
];

export const APPROVED_CATEGORIES = [
  "Approvals","Project Setup","Planning","Survey","Coordination","Design & Planning","Procurement","Logistics","Temporary Works","Civil","Masonry","Gypsum","Electrical","HVAC","Plumbing","Fire","Fire Alarm","Ceiling","Flooring","Painting","Furniture","Doors & Glass","IT & ELV","Data","Network","CCTV","Access Control","Security","Signage","Quality","Inspection","Testing","Documentation","As-Built Drawings","Handover Dossier","Housekeeping","Pending Items"
];

export const EXTERNAL_PARTIES = [
  "Client","Landlord","Building Management","Society","Consultant","Government Authority","Utility Provider","Other"
];

// The approval chain itself is derived on the project from the class and the
// person who actually does the work; this only explains it.
export const TASK_CLASS_OPTIONS = [
  { value:"standard", label:"Standard", detail:"Normal site work. If an Internal Employee does it, the Supervisor checks it. If the Supervisor does it, a PM or Admin checks it. Then it is complete." },
  { value:"class_a", label:"Class A", detail:"Important or high-risk work that needs an extra approval. If an Internal Employee does it, the Supervisor checks it and a PM or Admin approves it. If the Supervisor does it, a PM or Admin checks it, then a different PM or Admin approves." },
];

// Older task types, shown only on tasks that already use them.
export const TASK_KIND_LABELS = { work:"Ordinary work", approval_gate:"Approval task", milestone:"Milestone" };

// Only rules that produce a real due date (project_gate_due_date.resolve_gate_due_at),
// plus an honest "no due date". Imported rules show as "No due date" and are kept as-is.
export const WHEN_NEEDED_OPTIONS = [
  { value:"before_tasks", label:"Before the tasks it's required for", detail:"Due the day before the first of those tasks starts." },
  { value:"project_day", label:"By a project day", detail:"Due on a fixed day of the project." },
  { value:"none", label:"No due date", detail:"Set a date when assigning it on each project. Date-based overdue reminders won't apply until then." },
];

/** When an approval is due, in words; an imported rule shows its original wording. */
export function gateDueDateText(gate) {
  if (gate.required_by_type === "before_linked_tasks") return "Due the day before the first of them starts";
  if (gate.required_by_type === "project_day") return `Due by day ${gate.required_by_value}`;
  return gate.required_by_value ? `No due date (imported: "${gate.required_by_value}")` : "No due date";
}

export function whenNeededFor(requiredByType) {
  if (requiredByType === "before_linked_tasks") return "before_tasks";
  if (requiredByType === "project_day") return "project_day";
  return "none";
}

export function nextStructuredCode(items, prefix) {
  const values = items
    .map(item => String(item.code || "").toUpperCase())
    .map(code => new RegExp(`^${prefix}(\\d+)$`).exec(code))
    .filter(Boolean)
    .map(match => Number(match[1]));
  const next = (values.length ? Math.max(...values) : 0) + 1;
  return `${prefix}${String(next).padStart(3, "0")}`;
}
