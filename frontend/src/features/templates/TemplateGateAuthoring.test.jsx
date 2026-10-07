import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi",()=>({templatesApi:{getVersion:vi.fn(),listTasks:vi.fn(),listDependencies:vi.fn(),listGates:vi.fn(),createGate:vi.fn(),updateGate:vi.fn(),configureGateMappings:vi.fn(),deleteGate:vi.fn(),validateVersion:vi.fn(),publishVersion:vi.fn(),createTask:vi.fn(),updateTask:vi.fn(),deleteTask:vi.fn(),reorderTasks:vi.fn(),createDependency:vi.fn(),updateDependency:vi.fn(),deleteDependency:vi.fn()}}));
const summary={version_id:"draft-1",template_code:"TEST",template_name:"Test",version_no:2,status:"draft",duration_days:45,updated_at:"2026-07-28T10:00:00Z",revision_token:"rev-1"};
const tasks=[{id:"task-1",code:"T001",title:"Fire piping",sequence_no:1,planned_start_day:10},{id:"task-2",code:"T002",title:"Fire equipment installation",sequence_no:2,planned_start_day:12}];
// An imported gate: original wording kept as text, not linked to tasks, no usable due-date rule.
const broad={id:"gate-1",code:"E001",approval_name:"General approval",description:null,external_party:"Client",required_by_type:"source_text",required_by_value:"Before work",impact:"Blocks work",sequence_no:1,mapping_classification:"broad_text",broad_mapping_text:"Affected activities",requires_configuration:true,affected_tasks:[]};
const linked={...broad,id:"gate-2",code:"E002",approval_name:"Fire NOC",required_by_type:"before_linked_tasks",required_by_value:null,sequence_no:2,mapping_classification:"exact",broad_mapping_text:null,requires_configuration:false,affected_tasks:[tasks[0],tasks[1]]};
const page=items=>({items,pagination:{page:1,page_size:100,total:items.length,total_pages:items.length?1:0},summary:{total:0}});
function view(role="super_admin",s=summary){return render(<TemplateDraftEditorEntry summary={s} user={{role}} onBack={vi.fn()}/>)}
beforeEach(()=>{vi.clearAllMocks();templatesApi.getVersion.mockResolvedValue(summary);templatesApi.listTasks.mockResolvedValue(page(tasks));templatesApi.listDependencies.mockResolvedValue(page([]));templatesApi.listGates.mockResolvedValue(page([broad,linked]));templatesApi.createGate.mockResolvedValue({gate:broad,revision_token:"rev-2"});templatesApi.updateGate.mockResolvedValue({gate:broad,revision_token:"rev-2"});templatesApi.configureGateMappings.mockResolvedValue({gate:{...broad,mapping_classification:"exact",affected_tasks:[tasks[0]]},revision_token:"rev-3"});templatesApi.deleteGate.mockResolvedValue({gate_id:"gate-1",deleted:true,revision_token:"rev-2"});});
async function openApprovals(){view();await screen.findByTestId("draft-task-T001");fireEvent.click(screen.getByRole("button",{name:/prerequisite approvals/i}));return screen.findByTestId("draft-gate-gate-1");}
const addDialog=()=>{fireEvent.click(screen.getByRole("button",{name:/add approval/i}));return screen.getByRole("dialog",{name:/add prerequisite approval/i});};
const editDialog=code=>{fireEvent.click(screen.getAllByRole("button",{name:`Edit approval ${code}`})[0]);return screen.getByRole("dialog",{name:/edit prerequisite approval/i});};

describe("prerequisite approval authoring",()=>{
  it("creates an approval required before chosen tasks, due before the first of them",async()=>{
    await openApprovals();const d=addDialog();
    fireEvent.change(within(d).getByLabelText("Approval name"),{target:{value:"Fire NOC"}});
    fireEvent.change(within(d).getByLabelText("Who approves"),{target:{value:"Government Authority"}});
    fireEvent.click(within(d).getByLabelText("Required before T001"));
    fireEvent.click(within(d).getByLabelText("Required before T002"));
    expect(within(d).getByText("This approval is required before these tasks")).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button",{name:/add approval/i}));
    await waitFor(()=>expect(templatesApi.createGate).toHaveBeenCalledWith("draft-1",expect.objectContaining({
      approval_name:"Fire NOC",external_party:"Government Authority",code:"E003",sequence_no:3,
      required_by_type:"before_linked_tasks",required_by_value:null,
      mapping_classification:"exact",task_ids:["task-1","task-2"],broad_mapping_text:null,revision_token:"rev-1",
    })));
  });

  it("offers only due-date choices that mean something, and no import or blocking wording",async()=>{
    await openApprovals();const d=addDialog();
    const when=within(d).getByRole("radiogroup",{name:"When is it needed?"});
    expect(within(when).getAllByRole("radio").map(radio=>radio.getAttribute("aria-label"))).toEqual(["Before the tasks it's required for","By a project day","No due date"]);
    expect(within(d).queryByText(/pre-activation|before phase|before milestone|mapping classification|broad|unmapped|blocked/i)).not.toBeInTheDocument();
  });

  it("will not save a 'before its tasks' rule with no tasks, or a day outside the template",async()=>{
    await openApprovals();const d=addDialog();
    fireEvent.change(within(d).getByLabelText("Approval name"),{target:{value:"Fire NOC"}});
    fireEvent.click(within(d).getByRole("button",{name:/add approval/i}));
    expect(await within(d).findByText(/pick the tasks it's required before/i)).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("radio",{name:"By a project day"}));
    fireEvent.change(within(d).getByLabelText("Needed by day"),{target:{value:"46"}});
    fireEvent.click(within(d).getByRole("button",{name:/add approval/i}));
    expect(await within(d).findByText("Use Day 1-45.")).toBeInTheDocument();
    expect(templatesApi.createGate).not.toHaveBeenCalled();
  });

  it("saves an approval with no due date as a plain empty rule",async()=>{
    await openApprovals();const d=addDialog();
    fireEvent.change(within(d).getByLabelText("Approval name"),{target:{value:"Client sign-off"}});
    fireEvent.click(within(d).getByRole("radio",{name:"No due date"}));
    expect(within(d).getByText(/not linked to any task yet/i)).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button",{name:/add approval/i}));
    await waitFor(()=>expect(templatesApi.createGate).toHaveBeenCalledWith("draft-1",expect.objectContaining({required_by_type:null,required_by_value:null,mapping_classification:"unmapped",task_ids:[]})));
  });

  it("shows an imported approval truthfully and keeps it unchanged unless the Admin changes it",async()=>{
    await openApprovals();
    const card=screen.getByTestId("draft-gate-gate-1");
    expect(card).toHaveTextContent("Affected activities");
    expect(card).toHaveTextContent("Not linked to any task");
    expect(card).toHaveTextContent("No due date");
    const d=editDialog("E001");
    expect(within(d).getByText("Imported wording kept, no due date")).toBeInTheDocument();
    expect(within(d).getByText("Before work")).toBeInTheDocument();
    expect(within(d).getByRole("radio",{name:"No due date"})).toBeChecked();
    fireEvent.change(within(d).getByLabelText("Approval name"),{target:{value:"Client approval"}});
    fireEvent.click(within(d).getByRole("button",{name:/save approval/i}));
    await waitFor(()=>expect(templatesApi.updateGate).toHaveBeenCalledWith("draft-1","gate-1",{revision_token:"rev-1",approval_name:"Client approval"}));
    expect(templatesApi.configureGateMappings).not.toHaveBeenCalled();
  });

  it("linking tasks to an imported approval replaces its wording, with a clear notice",async()=>{
    await openApprovals();const d=editDialog("E001");
    fireEvent.click(within(d).getByLabelText("Required before T001"));
    expect(within(d).getByText(/replaces the imported wording/i)).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button",{name:/save approval/i}));
    await waitFor(()=>expect(templatesApi.configureGateMappings).toHaveBeenCalledWith("draft-1","gate-1",{mapping_classification:"exact",broad_mapping_text:null,task_ids:["task-1"],revision_token:"rev-1"}));
  });

  it("shows what a linked approval is required before",async()=>{
    await openApprovals();
    const card=screen.getByTestId("draft-gate-gate-2");
    expect(card).toHaveTextContent("Required before 2 tasks");
    expect(card).toHaveTextContent("Due the day before the first of them starts");
  });

  it("deletes only the approval",async()=>{
    await openApprovals();fireEvent.click(screen.getAllByRole("button",{name:/delete approval E001/i})[0]);
    const d=screen.getByRole("dialog",{name:/delete E001/i});expect(within(d).getByText(/Tasks are not deleted/i)).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button",{name:/^delete approval$/i}));
    await waitFor(()=>expect(templatesApi.deleteGate).toHaveBeenCalledWith("draft-1","gate-1","rev-1"));
  });

  it("shows stale errors and keeps published/non-admin drafts read-only",async()=>{
    templatesApi.createGate.mockRejectedValue({details:{detail:{code:"stale_template_version"}}});
    await openApprovals();const d=addDialog();
    fireEvent.change(within(d).getByLabelText("Approval name"),{target:{value:"Approval"}});
    fireEvent.click(within(d).getByRole("radio",{name:"No due date"}));
    fireEvent.click(within(d).getByRole("button",{name:/add approval/i}));
    expect(await within(d).findByText(/changed in another session/i)).toBeInTheDocument();
    cleanup();view("project_manager");expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
    cleanup();const published={...summary,status:"published"};templatesApi.getVersion.mockResolvedValue(published);view("super_admin",published);expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
  });

  it("uses full-width mobile actions",async()=>{
    await openApprovals();expect(screen.getByRole("button",{name:/add approval/i})).toHaveClass("w-full");
    const d=addDialog();expect(within(d).getByRole("button",{name:/add approval/i})).toHaveClass("w-full");
  });
});
