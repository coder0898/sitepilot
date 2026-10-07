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

export const REQUIRED_BY_TYPES = [
  ["pre_activation","Pre-Activation"],
  ["project_day","Project Day"],
  ["before_task","Before Task"],
  ["before_phase","Before Phase"],
  ["before_milestone","Before Milestone"],
  ["other","Other"]
];

export function nextStructuredCode(items, prefix) {
  const values = items
    .map(item => String(item.code || "").toUpperCase())
    .map(code => new RegExp(`^${prefix}(\\d+)$`).exec(code))
    .filter(Boolean)
    .map(match => Number(match[1]));
  const next = (values.length ? Math.max(...values) : 0) + 1;
  return `${prefix}${String(next).padStart(3, "0")}`;
}
