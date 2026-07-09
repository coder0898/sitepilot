import { AlertTriangle } from "lucide-react";
import { Modal } from "./Modal";

export function ConfirmModal({ title = "Confirm action", message, confirmLabel = "Confirm", tone = "danger", onConfirm, onClose }) {
  return (
    <Modal title={title} subtitle="Please confirm before continuing" onClose={onClose}>
      <div className="confirm-dialog">
        <p>{message}</p>
        <div className="confirm-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="button" className={tone === "danger" ? "danger" : ""} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </Modal>
  );
}
