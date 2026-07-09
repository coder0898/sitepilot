export function ManagementHeader({ eyebrow, title, subtitle, actionLabel, actionIcon, onAction }) {
  return (
    <section className="management-page-head">
      <div>
        <p>{eyebrow}</p>
        <h2>{title}</h2>
        <span>{subtitle}</span>
      </div>
      {actionLabel && <button type="button" onClick={onAction}>{actionIcon}{actionLabel}</button>}
    </section>
  );
}
