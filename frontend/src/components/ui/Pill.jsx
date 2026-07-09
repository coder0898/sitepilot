export function Pill({ children, tone = "blue" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
