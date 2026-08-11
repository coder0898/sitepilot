export function fmtStatus(value) {
  const labels = {
    pending: "Pending",
    in_progress: "In Progress",
    submitted: "Submitted for Approval",
    completed: "Approved",
    rejected: "Rejected",
    delayed: "Delayed",
    blocked: "Blocked",
  };
  return labels[value] || value?.replaceAll("_", " ") || "Pending";
}

export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function initials(name = "") {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "SO";
}

export function formatDateShort(value) {
  return value
    ? new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
    : "—";
}

// Compact relative age for list rows, from an ISO timestamp. Deliberately
// coarse - "2h ago" is the useful signal, minute precision is noise.
export function relativeAge(value, now = Date.now()) {
  if (!value) return null;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return null;
  const minutes = Math.floor((now - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export function statusTone(status) {
  if (status === "completed") return "green";
  if (status === "submitted") return "yellow";
  if (["blocked", "delayed", "rejected"].includes(status)) return "red";
  if (status === "in_progress") return "blue";
  return "gray";
}
