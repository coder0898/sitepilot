export const APPROVED_PHASES = [
  "Pre-Activation","Mobilisation","Coordination","Survey","Planning","Design & Planning","Shop Drawings","Procurement","Off-Site Production","Dismantling","Civil","Partitions","MEP First Fix","Floor Base","Ceiling","Carpentry","Doors & Glass","MEP Second Fix","Fire Second Fix","Flooring","Painting","Furniture","IT & ELV","Security","Testing","Inspection","Snagging","Rectification","Cleaning","Documentation","Handover","Demobilisation"
];

export const APPROVED_CATEGORIES = [
  "Approvals","Project Setup","Planning","Survey","Coordination","Design & Planning","Procurement","Logistics","Temporary Works","Civil","Masonry","Gypsum","Electrical","HVAC","Plumbing","Fire","Fire Alarm","Ceiling","Flooring","Painting","Furniture","Doors & Glass","IT & ELV","Data","Network","CCTV","Access Control","Security","Signage","Quality","Inspection","Testing","Documentation","As-Built Drawings","Handover Dossier","Housekeeping","Pending Items"
];

export const EXTERNAL_PARTIES = [
  "Client","Landlord","Building Management","Society","Consultant","Government Authority","Utility Provider","Other"
];

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
