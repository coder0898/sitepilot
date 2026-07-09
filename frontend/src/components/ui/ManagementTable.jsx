import { SlidersHorizontal } from "lucide-react";
import { Pill } from "./Pill";

export function ManagementTable({
  countLabel,
  count,
  searchPlaceholder,
  tableClassName = "",
  children,
}) {
  return (
    <section className="panel management-card">
      <div className="management-toolbar">
        <div className="count-label">
          {countLabel} <Pill>{count}</Pill>
        </div>

        <div className="table-tools">
          <input placeholder={searchPlaceholder} readOnly />
          <button type="button" className="ghost-button">
            <SlidersHorizontal size={17} /> Filters
          </button>
        </div>
      </div>

      <div className="table-scroll">
        <table className={`data-table ${tableClassName}`.trim()}>
          {children}
        </table>
      </div>
    </section>
  );
}