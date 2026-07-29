import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi",()=>({templatesApi:{
  getVersion:vi.fn(),listTasks:vi.fn(),listDependencies:vi.fn(),listGates:vi.fn(),createTask:vi.fn(),updateTask:vi.fn(),deleteTask:vi.fn(),reorderTasks:vi.fn(),
}}));

const summary={version_id:"draft-1",template_code:"TEST-45",template_name:"Test schedule",version_no:2,status:"draft",duration_days:45,task_count:2,dependency_count:1,gate_count:1,updated_at:"2026-07-28T10:00:00Z",revision_token:"rev-1"};
const tasks=[
  {id:"task-1",template_version_id:"draft-1",code:"T001",sequence_no:1,title:"Confirm site",description:null,schedule_classification:"pre_activation",planned_start_day:null,planned_end_day:null,phase:"Activation",category:"Governance",applicability:"mandatory",task_class:null,task_kind:null,evidence_required:false,duration_days:null,validation_state:"valid",validation_issues:[]},
  {id:"task-2",template_version_id:"draft-1",code:"T002",sequence_no:2,title:"Start work",description:null,schedule_classification:"execution",planned_start_day:1,planned_end_day:1,phase:"Execution",category:"Site",applicability:"mandatory",task_class:null,task_kind:null,evidence_required:false,duration_days:1,validation_state:"valid",validation_issues:[]},
];
const page=items=>({items,pagination:{page:1,page_size:100,total:items.length,total_pages:items.length?1:0}});
const mutation=(task,revision_token="rev-2")=>({task,revision_token});

function view(role="super_admin"){return render(<TemplateDraftEditorEntry summary={summary} user={{role}} onBack={vi.fn()}/>);}

beforeEach(()=>{
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page(tasks));
  templatesApi.listDependencies.mockResolvedValue(page([]));
  templatesApi.listGates.mockResolvedValue(page([]));
  templatesApi.createTask.mockResolvedValue(mutation({...tasks[1],id:"task-3",code:"T003",sequence_no:3,title:"New task"}));
  templatesApi.updateTask.mockResolvedValue(mutation({...tasks[1],title:"Updated work"}));
  templatesApi.deleteTask.mockResolvedValue({task_id:"task-2",deleted:true,revision_token:"rev-2"});
  templatesApi.reorderTasks.mockResolvedValue({items:[{task_id:"task-2",code:"T002",sequence_no:1},{task_id:"task-1",code:"T001",sequence_no:2}],revision_token:"rev-2"});
});

describe("draft task authoring",()=>{
  it("deduplicates the initial draft load under React StrictMode",async()=>{
    render(<StrictMode><TemplateDraftEditorEntry summary={summary} user={{role:"super_admin"}} onBack={vi.fn()}/></StrictMode>);
    expect(await screen.findByText("Draft task authoring")).toBeInTheDocument();
    await screen.findByTestId("draft-task-T001");
    expect(templatesApi.getVersion).toHaveBeenCalledTimes(1);
    expect(templatesApi.listTasks).toHaveBeenCalledTimes(1);
  });

  it("shows authoring only for a Super Admin draft",async()=>{
    view();
    expect(await screen.findByText("Draft task authoring")).toBeInTheDocument();
    expect(screen.getByRole("button",{name:/add task/i})).toBeInTheDocument();
    const denied=view("admin");
    expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
    denied.unmount();
  });

  it("validates execution days and creates a task with the current revision",async()=>{
    view(); await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getByRole("button",{name:/add task/i}));
    const dialog=screen.getByRole("dialog",{name:/add draft task/i});
    fireEvent.change(within(dialog).getByLabelText("Task code"),{target:{value:"T003"}});
    fireEvent.change(within(dialog).getByLabelText("Task title"),{target:{value:"New task"}});
    fireEvent.change(within(dialog).getByLabelText("Planned start day"),{target:{value:"46"}});
    fireEvent.change(within(dialog).getByLabelText("Planned end day"),{target:{value:"44"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/add task/i}));
    expect(await within(dialog).findByText("Use Day 1-45.")).toBeInTheDocument();
    expect(within(dialog).getByText("End day cannot precede start day.")).toBeInTheDocument();
    expect(templatesApi.createTask).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Planned start day"),{target:{value:"2"}});
    fireEvent.change(within(dialog).getByLabelText("Planned end day"),{target:{value:"3"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/add task/i}));
    await waitFor(()=>expect(templatesApi.createTask).toHaveBeenCalledWith("draft-1",expect.objectContaining({code:"T003",sequence_no:3,planned_start_day:2,planned_end_day:3,revision_token:"rev-1"})));
  });

  it("edits a task and sends the revision token",async()=>{
    view(); await screen.findByTestId("draft-task-T002");
    fireEvent.click(screen.getAllByRole("button",{name:"Edit T002"})[0]);
    const dialog=screen.getByRole("dialog",{name:/edit draft task/i});
    fireEvent.change(within(dialog).getByLabelText("Task title"),{target:{value:"Updated work"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/save task/i}));
    await waitFor(()=>expect(templatesApi.updateTask).toHaveBeenCalledWith("draft-1","task-2",expect.objectContaining({title:"Updated work",revision_token:"rev-1"})));
  });

  it("surfaces dependency and gate conflicts without deleting references",async()=>{
    templatesApi.deleteTask.mockRejectedValue({status:409,message:"Referenced",details:{detail:{code:"template_task_referenced",dependencies:[{dependency_id:"dep-1",relationship:"successor",other_task_id:"task-1"}],gate_mappings:[{id:"map-1",gate_code:"E001"}]}}});
    view(); await screen.findByTestId("draft-task-T002");
    fireEvent.click(screen.getAllByRole("button",{name:"Delete T002"})[0]);
    fireEvent.click(screen.getByRole("button",{name:/delete task/i}));
    expect(await screen.findByText("Task is still referenced")).toBeInTheDocument();
    expect(screen.getByText("successor · related task task-1")).toBeInTheDocument();
    expect(screen.getByText("E001")).toBeInTheDocument();
  });

  it("reorders all tasks atomically and can cancel a local order",async()=>{
    view(); await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getAllByRole("button",{name:"Move T001 down"})[0]);
    expect(screen.getByText(/order changed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:/save order/i}));
    await waitFor(()=>expect(templatesApi.reorderTasks).toHaveBeenCalledWith("draft-1",{revision_token:"rev-1",items:[{task_id:"task-2",sequence_no:1},{task_id:"task-1",sequence_no:2}]}));
  });

  it("shows stale-revision feedback and keeps the editor open",async()=>{
    templatesApi.updateTask.mockRejectedValue({status:409,message:"Conflict",details:{detail:{code:"stale_template_version"}}});
    view(); await screen.findByTestId("draft-task-T002");
    fireEvent.click(screen.getAllByRole("button",{name:"Edit T002"})[0]);
    const dialog=screen.getByRole("dialog",{name:/edit draft task/i});
    fireEvent.change(within(dialog).getByLabelText("Task title"),{target:{value:"Changed"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/save task/i}));
    expect(await within(dialog).findByText(/changed in another session/i)).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
  });

  it("warns before discarding unsaved mobile-friendly form changes",async()=>{
    const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
    view(); await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getByRole("button",{name:/add task/i}));
    const dialog=screen.getByRole("dialog",{name:/add draft task/i});
    fireEvent.change(within(dialog).getByLabelText("Task code"),{target:{value:"T004"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/cancel/i}));
    expect(confirm).toHaveBeenCalledWith("Discard unsaved task changes?");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole("button",{name:/add task/i})).toHaveClass("w-full");
    confirm.mockRestore();
  });
});
