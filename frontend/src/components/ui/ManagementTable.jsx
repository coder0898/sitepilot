import { LayoutGrid, SlidersHorizontal } from "lucide-react";
import { Pill } from "./Pill";

export function ManagementTable({ countLabel, count, searchPlaceholder, children, showGrid = false }) {
  return (
    <section className="panel management-card">
      <div className="management-toolbar">
        <div className="count-label">{countLabel} <Pill>{count}</Pill></div>
        <div className="table-tools">
          <input placeholder={searchPlaceholder} readOnly />
          <button type="button" className="ghost-button"><SlidersHorizontal size={17} /> Filters</button>
          {showGrid && <button type="button" className="icon-button" aria-label="Grid view"><LayoutGrid size={18} /></button>}
        </div>
      </div>

      {/* Children container now uses a table structure instead of divs */}
      <table className="management-table">
        {children}
      </table>
    </section>
  );
}