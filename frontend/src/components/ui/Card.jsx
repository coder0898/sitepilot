export function Card({ children, className = "" }) {
  return <section className={`panel ${className}`}>{children}</section>;
}
