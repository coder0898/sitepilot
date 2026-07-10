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

export function statusTone(status) {
  if (status === "completed") return "green";
  if (status === "submitted") return "yellow";
  if (["blocked", "delayed", "rejected"].includes(status)) return "red";
  if (status === "in_progress") return "blue";
  return "gray";
}
