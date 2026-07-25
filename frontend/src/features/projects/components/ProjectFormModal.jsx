import { CalendarDays, ClipboardList, MapPin, UsersRound } from "lucide-react";
import { Button, Field, FormGrid, FormSection, Input, Modal, Select, Textarea } from "../../../components/ui";

function memberOptions(items, placeholder) {
  return <><option value="">{placeholder}</option>{items.map(item => <option key={item.employee_id} value={item.employee_id}>{item.name} · {item.designation}</option>)}</>;
}

export function ProjectFormModal({ project, references, onClose, onSubmit, saving }) {
  const editing = Boolean(project);
  async function submit(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const payload = {
      name: values.name,
      client_name: values.client_name,
      site_address: values.site_address,
      description: values.description || null,
      start_date: values.start_date,
      target_handover_date: values.target_handover_date || null,
      reason: values.reason || "Project details updated.",
    };
    if (!editing) Object.assign(payload, {
      code: values.code,
      project_manager_employee_id: values.project_manager_employee_id || null,
      supervisor_employee_id: values.supervisor_employee_id || null,
      assignment_reason: values.assignment_reason || null,
    });
    await onSubmit(payload);
  }

  return <Modal title={editing ? "Edit project" : "Create project"} subtitle={editing ? "Update project identity and planned dates." : "Start with a controlled draft. The approved template will generate its 45-day schedule later."} onClose={onClose} className="sm:max-w-4xl">
    <form className="grid gap-4" onSubmit={submit}>
      <FormSection title="Project identity" description="The permanent code keeps this project traceable across schedules and reports." icon={ClipboardList}>
        <FormGrid>
          {!editing && <Field label="Project code" hint="3–30 uppercase letters, numbers or hyphens."><Input name="code" required placeholder="WVS-MUM-001" autoComplete="off" /></Field>}
          <Field label="Project name"><Input name="name" required defaultValue={project?.name || ""} placeholder="Head office interior fit-out" /></Field>
          <Field label="Client"><Input name="client_name" required defaultValue={project?.client_name || ""} placeholder="Client or organisation name" /></Field>
          <Field label="Site address" className="md:col-span-2"><Textarea name="site_address" required defaultValue={project?.site_address || ""} placeholder="Building, floor, street, city and postcode" /></Field>
          <Field label="Project brief" hint="Keep this operational and concise." className="md:col-span-2"><Textarea name="description" defaultValue={project?.description || ""} placeholder="Scope, constraints or key site context" /></Field>
        </FormGrid>
      </FormSection>

      <FormSection title="Planned window" description="The handover date is optional until the approved 45-day template is attached." icon={CalendarDays}>
        <FormGrid>
          <Field label="Start date"><Input type="date" name="start_date" required defaultValue={project?.start_date || ""} /></Field>
          <Field label="Target handover date (optional)" hint="If blank, the future template will calculate start date + 44 days."><Input type="date" name="target_handover_date" defaultValue={project?.target_handover_date || ""} /></Field>
        </FormGrid>
      </FormSection>

      {!editing && <FormSection title="Initial accountability" description="These assignments can be completed later while the project remains draft." icon={UsersRound}>
        <FormGrid>
          <Field label="Project Manager"><Select name="project_manager_employee_id">{memberOptions(references.project_managers || [], "Assign later")}</Select></Field>
          <Field label="Site Supervisor"><Select name="supervisor_employee_id">{memberOptions(references.supervisors || [], "Assign later")}</Select></Field>
          <Field label="Assignment reason" hint="Required operational context when a team is selected." className="md:col-span-2"><Input name="assignment_reason" placeholder="Initial project setup" /></Field>
        </FormGrid>
      </FormSection>}

      {editing && <Field label="Reason for change"><Input name="reason" required minLength={4} placeholder="Why are these project details changing?" /></Field>}
      <div className="sticky -bottom-6 -mx-4 mt-1 flex justify-end gap-2 border-t border-slate-100 bg-white/95 px-4 py-4 backdrop-blur sm:-mx-6 sm:px-6">
        <Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving}>{editing ? "Save changes" : "Create draft"}</Button>
      </div>
    </form>
  </Modal>;
}
