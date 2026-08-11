import { CalendarDays, ClipboardList, MapPin, UsersRound } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Field, FormGrid, FormSection, Input, Modal, Select, Textarea } from "../../../components/ui";

// Mirrors derive_target_handover_date in backend/app/routes/projects_v2.py.
// Day 1 of the schedule is the start date itself, so a 45-day template
// starting 11 Aug hands over on 24 Sep - start + 44, not start + 45. The
// server recomputes this on save; what is rendered here is only a preview.
export function derivedHandoverDate(startDate, template) {
  if (!startDate || !template?.duration_days) return null;
  const handover = new Date(`${startDate}T00:00:00`);
  if (Number.isNaN(handover.getTime())) return null;
  handover.setDate(handover.getDate() + template.duration_days - 1);
  return handover;
}

function userOptions(items, placeholder) {
  return <><option value="">{placeholder}</option>{items.map(item => <option key={item.user_id} value={item.user_id}>{item.name} - {item.designation}</option>)}</>;
}

function templateOptions(items) {
  return <><option value="">Select published template</option>{items.map(item => (
    <option key={item.version_id} value={item.version_id}>
      {item.template_name} - v{item.version_no} - {item.duration_days} days{item.is_current_published ? " - Current" : ""}
    </option>
  ))}</>;
}

function validateCreate(values) {
  const errors = {};
  if (!values.name.trim()) errors.name = "Project name is required.";
  if (!values.client_name.trim()) errors.client_name = "Client is required.";
  if (!values.site_address.trim()) errors.site_address = "Location is required.";
  if (!values.start_date) errors.start_date = "Proposed start date is required.";
  if (!values.project_manager_user_id) errors.project_manager_user_id = "Select an active Project Manager.";
  if (!values.supervisor_user_id) errors.supervisor_user_id = "Select an active Supervisor.";
  if (!values.template_version_id) errors.template_version_id = "Select a published template version.";
  return errors;
}

function setFieldErrors(form, errors) {
  form.querySelectorAll("[data-field-error]").forEach(node => { node.textContent = ""; });
  Object.entries(errors).forEach(([name, message]) => {
    const node = form.querySelector(`[data-field-error="${name}"]`);
    if (node) node.textContent = message;
  });
  form.querySelector(`[name="${Object.keys(errors)[0]}"]`)?.focus();
}

export function ProjectFormModal({ project = null, references, templates = [], templatesLoading = false, templatesError = "", onClose, onSubmit, saving, apiError = "" }) {
  const editing = Boolean(project);
  // The rest of the form stays uncontrolled and is read via FormData on
  // submit. These two are tracked because the handover preview has to
  // recompute as either one changes.
  const [startDate, setStartDate] = useState(project?.start_date || "");
  const [templateVersionId, setTemplateVersionId] = useState(project?.template_version_id || "");

  const selectedTemplate = templates.find(item => item.version_id === templateVersionId) || null;
  const handover = derivedHandoverDate(startDate, selectedTemplate);
  const handoverLabel = handover
    ? handover.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
    : null;

  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    // A disabled input is omitted from FormData, and the start date is
    // disabled once a template is attached - so read it from state, which is
    // the source of truth for this field in both modes. The template select
    // is deliberately NOT patched in the same way: when it is disabled the
    // backend must not receive template_version_id at all, or editing an
    // active project 409s on "a template can only be attached while draft".
    values.start_date = startDate;

    if (editing) {
      const errors = {};
      if (!values.name.trim()) errors.name = "Project name is required.";
      if (!values.client_name.trim()) errors.client_name = "Client is required.";
      if (!values.site_address.trim()) errors.site_address = "Location is required.";
      if (!values.start_date) errors.start_date = "Proposed start date is required.";
      if (project?.status === "draft" && !project?.template_version_id && !values.template_version_id) errors.template_version_id = "Select a published template version.";
      if (Object.keys(errors).length) { setFieldErrors(form, errors); return; }
      await onSubmit({
        name: values.name.trim(),
        client_name: values.client_name.trim(),
        site_address: values.site_address.trim(),
        description: values.description?.trim() || null,
        start_date: values.start_date,
        // Handover is never sent: the server derives it from the template
        // duration and rejects an explicit value outright.
        ...(values.template_version_id ? { template_version_id: values.template_version_id } : {}),
        reason: values.reason.trim(),
      });
      return;
    }

    const errors = validateCreate(values);
    if (Object.keys(errors).length) {
      setFieldErrors(form, errors);
      return;
    }
    await onSubmit({
      name: values.name.trim(),
      client_name: values.client_name.trim(),
      site_address: values.site_address.trim(),
      start_date: values.start_date,
      project_manager_user_id: values.project_manager_user_id,
      supervisor_user_id: values.supervisor_user_id,
      template_version_id: values.template_version_id,
    });
  }

  return <Modal title={editing ? "Edit project" : "Create draft project"} subtitle={editing ? "Update project identity and planned dates." : "Create only the controlled project shell. Template tasks are not generated at this stage."} onClose={saving ? undefined : onClose} className="sm:max-w-4xl">
    <form className="grid min-w-0 gap-4" onSubmit={submit} noValidate={!editing}>
      {apiError && <Alert tone="danger">{apiError}</Alert>}
      <fieldset disabled={saving} className="grid min-w-0 gap-4 disabled:opacity-75">
        <FormSection title="Project identity" description={editing ? "Update the project record without changing its template baseline." : "Enter the project, client and physical location."} icon={ClipboardList}>
          <FormGrid>
            <Field label="Project name" htmlFor="project-name"><Input id="project-name" name="name" required defaultValue={project?.name || ""} autoComplete="off" placeholder="Head office interior fit-out" aria-describedby="name-error"/><small id="name-error" data-field-error="name" className="font-medium text-rose-600"/></Field>
            <Field label="Client" htmlFor="project-client"><Input id="project-client" name="client_name" required defaultValue={project?.client_name || ""} autoComplete="organization" placeholder="Client or organisation name" aria-describedby="client-error"/><small id="client-error" data-field-error="client_name" className="font-medium text-rose-600"/></Field>
            <Field label="Location" htmlFor="project-location" className="md:col-span-2">{editing ? <Textarea id="project-location" name="site_address" required defaultValue={project?.site_address || ""} placeholder="Building, floor, city"/> : <Input id="project-location" name="site_address" required autoComplete="street-address" placeholder="Building, floor, city" aria-describedby="location-error"/>}<small id="location-error" data-field-error="site_address" className="font-medium text-rose-600"/></Field>
            {editing && <Field label="Project brief" htmlFor="project-description" className="md:col-span-2"><Textarea id="project-description" name="description" defaultValue={project?.description || ""}/></Field>}
          </FormGrid>
        </FormSection>

        <FormSection title="Planned start" description={editing ? "Update the planned dates with an audit reason." : "This is the proposed Day 1 date for the future project schedule."} icon={CalendarDays}>
          <FormGrid>
            <Field label="Proposed start date" htmlFor="project-start-date">
              <Input
                id="project-start-date"
                type="date"
                name="start_date"
                required
                value={startDate}
                onChange={event => setStartDate(event.target.value)}
                disabled={editing && Boolean(project?.template_version_id)}
                aria-describedby="start-date-help start-date-error"
              />
              {editing && project?.template_version_id
                ? <small id="start-date-help" className="text-xs text-slate-500">Locked: the start date cannot move once a template is attached.</small>
                : null}
              <small id="start-date-error" data-field-error="start_date" className="font-medium text-rose-600"/>
            </Field>
            {/* Derived, never entered - the server computes the same value
                from the template duration and rejects a supplied one. */}
            <Field label="Target handover date" htmlFor="project-target-date">
              <output
                id="project-target-date"
                aria-live="polite"
                className="flex min-h-12 items-center rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm font-bold text-slate-700"
              >
                {handoverLabel || "Select a start date and template"}
              </output>
              <small className="text-xs text-slate-500">
                {selectedTemplate
                  ? `Calculated automatically — day ${selectedTemplate.duration_days} of ${selectedTemplate.template_name}, counting the start date as day 1.`
                  : "Calculated automatically from the start date and the template's duration."}
              </small>
            </Field>
          </FormGrid>
        </FormSection>

        {(!editing || project?.status === "draft") && <FormSection title="Approved published template" description={editing && project?.template_version_id ? "This draft already references an approved published version. The reference is locked after attachment." : "Select the approved published version for this draft. Tasks are not generated by this action."} icon={MapPin}>
          <Field label="Published template version" htmlFor="project-template-version">
            <Select
              id="project-template-version"
              name="template_version_id"
              required={!editing || !project?.template_version_id}
              value={templateVersionId}
              onChange={event => setTemplateVersionId(event.target.value)}
              disabled={templatesLoading || Boolean(editing && project?.template_version_id)}
              aria-describedby="template-help template-error"
            >
              {templatesLoading
                ? <option value="">Loading published templates...</option>
                : templateOptions(templates)}
            </Select>
            <small id="template-help" className="text-xs text-slate-500">
              {templatesError
                ? templatesError
                : !templatesLoading && templates.length === 0
                  ? "No published template is available. Publish a template before creating or completing a draft project."
                  : editing && project?.template_version_id
                    ? "Template changes are locked to protect the project baseline."
                    : "Only published versions are listed."}
            </small>
            <small id="template-error" data-field-error="template_version_id" className="font-medium text-rose-600"/>
          </Field>
        </FormSection>}

        {!editing && <>
          <FormSection title="Accountability" description="Only active users with the correct role are available." icon={UsersRound}>
            <FormGrid>
              <Field label="Project Manager" htmlFor="project-manager"><Select id="project-manager" name="project_manager_user_id" required aria-describedby="pm-error">{userOptions(references.project_managers || [], "Select Project Manager")}</Select><small id="pm-error" data-field-error="project_manager_user_id" className="font-medium text-rose-600"/></Field>
              <Field label="Supervisor" htmlFor="project-supervisor"><Select id="project-supervisor" name="supervisor_user_id" required aria-describedby="supervisor-error">{userOptions(references.supervisors || [], "Select Supervisor")}</Select><small id="supervisor-error" data-field-error="supervisor_user_id" className="font-medium text-rose-600"/></Field>
            </FormGrid>
          </FormSection>

        </>}

        {editing && <Field label="Reason for change" htmlFor="project-change-reason"><Input id="project-change-reason" name="reason" required minLength={4} placeholder="Why are these project details changing?"/></Field>}
      </fieldset>

      <div className="sticky -bottom-6 -mx-4 mt-1 flex flex-col-reverse gap-2 border-t border-slate-100 bg-white/95 px-4 py-4 backdrop-blur sm:-mx-6 sm:flex-row sm:justify-end sm:px-6">
        <Button variant="secondary" onClick={onClose} disabled={saving} className="w-full sm:w-auto">Cancel</Button>
        <Button type="submit" loading={saving} className="w-full sm:w-auto">{editing ? "Save changes" : "Create draft"}</Button>
      </div>
    </form>
  </Modal>;
}
