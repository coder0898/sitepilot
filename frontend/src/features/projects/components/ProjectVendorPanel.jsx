import { Building2, RotateCcw, Truck } from "lucide-react";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, EmptyState, Field, Pill, Select } from "../../../components/ui";

const engagementLabel = { main: "Main vendor", sub_vendor: "Sub-vendor" };

// U2: map an active vendor to the project (R2). A sub-vendor additionally
// requires its parent vendor's mapping to already exist on this same
// project - the backend enforces this (422), this panel surfaces which
// candidates satisfy it up front so the PM isn't guessing.
export function ProjectVendorPanel({ project, user }) {
  const [allVendors, setAllVendors] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendorId, setVendorId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const canManage = ["admin", "super_admin", "project_manager"].includes(user.role);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [vendors, projectMappings] = await Promise.all([
        vendorAssignmentApi.listVendors(),
        vendorAssignmentApi.listProjectVendors(project.id),
      ]);
      setAllVendors(vendors);
      setMappings(projectMappings);
    } catch (caught) {
      setError(caught?.message || "Unable to load project vendors.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [project.id]);

  const mappedVendorIds = new Set(mappings.map(m => m.vendor_id));
  const candidates = allVendors.filter(v => !mappedVendorIds.has(v.id)).map(v => ({
    ...v,
    parentMapped: v.engagement_type !== "sub_vendor" || mappedVendorIds.has(v.parent_vendor_id),
  }));

  async function map(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.mapVendor(project.id, { vendor_id: vendorId });
      setVendorId("");
      await load();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be mapped to the project.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm font-bold text-slate-500">Loading project vendors...</div>;

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Truck size={18}/></span><div><h3 className="font-black text-slate-950">Project vendors</h3><p className="mt-1 text-xs leading-5 text-slate-500">Vendors mapped here can be delegated a task from the execution board.</p></div></div>
    </section>

    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error} <Button variant="secondary" className="ml-2" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}

    {mappings.length === 0 ? <EmptyState icon={<Truck size={20}/>} title="No vendors mapped yet" description="Map an active vendor to make it available for task delegation."/> : <div className="grid gap-2">{mappings.map(mapping => <article key={mapping.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3 text-sm"><div className="flex items-center gap-2"><Building2 size={15} className="text-slate-400"/><strong className="text-slate-900">{mapping.vendor_name}</strong><Pill tone="gray">{engagementLabel[mapping.engagement_type] || mapping.engagement_type}</Pill></div><time className="text-xs text-slate-400">{new Date(mapping.created_at).toLocaleDateString("en-GB")}</time></article>)}</div>}

    {canManage && <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5">
      <h4 className="text-xs font-black uppercase tracking-wide text-blue-800">Map a vendor</h4>
      <form className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end" onSubmit={map}>
        <Field label="Vendor">
          <Select value={vendorId} onChange={event => setVendorId(event.target.value)} required>
            <option value="">{candidates.length ? "Select vendor" : "No unmapped active vendors"}</option>
            {candidates.map(candidate => <option key={candidate.id} value={candidate.id} disabled={!candidate.parentMapped}>
              {candidate.name} · {engagementLabel[candidate.engagement_type] || candidate.engagement_type}{candidate.capability_categories.length ? ` (${candidate.capability_categories.join(", ")})` : ""}{!candidate.parentMapped ? " - parent not mapped" : ""}
            </option>)}
          </Select>
        </Field>
        <Button type="submit" loading={submitting} disabled={!vendorId}>Map vendor</Button>
      </form>
    </section>}
  </div>;
}
