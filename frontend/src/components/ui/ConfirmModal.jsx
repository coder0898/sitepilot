import { AlertTriangle } from "lucide-react";
import { Button } from "./Button";
import { Modal } from "./Modal";
export function ConfirmModal({ title, message, confirmLabel = "Confirm", onClose, onConfirm, tone = "danger", confirmDisabled = false }) {
  return <Modal title={title} onClose={onClose} className="max-w-md"><div className="flex gap-4"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-rose-50 text-rose-700"><AlertTriangle size={22}/></span><p className="pt-1 text-sm leading-6 text-slate-600">{message}</p></div><div className="mt-6 flex justify-end gap-3"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={tone === "danger" ? "danger" : "primary"} disabled={confirmDisabled} onClick={onConfirm}>{confirmLabel}</Button></div></Modal>;
}
