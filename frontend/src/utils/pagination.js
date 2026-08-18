// Compact page-number list with ellipsis for large page counts, e.g.
// [1, 2, "...", 6, 7, 8, "...", 22]. Shared by any list view with
// client-side pagination so the truncation rule stays in one place.
export function paginationItems(page, totalPages) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
  const items = new Set([1, 2, totalPages - 1, totalPages, page - 1, page, page + 1]);
  const sorted = [...items].filter(n => n >= 1 && n <= totalPages).sort((a, b) => a - b);
  const result = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) result.push("...");
    result.push(n);
  });
  return result;
}
