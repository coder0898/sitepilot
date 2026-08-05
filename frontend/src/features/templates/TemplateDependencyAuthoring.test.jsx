import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi",()=>({templatesApi:{
  getVersion:vi.fn(),listTasks:vi.fn(),listDependencies:vi.fn(),listGates:vi.fn(),createDependency:vi.fn(),updateDependency:vi.fn(),deleteDependency:vi.fn(),
  createTask:vi.fn(),updateTask:vi.fn(),deleteTask:vi.fn(),reorderTasks:vi.fn(),
}}));

const summary={version_id:"draft-1",template_code:"TEST-45",template_name:"Test schedule",version_no:2,status:"draft",duration_days:45,task_count:3,dependency_count:1,gate_count:0,updated_at:"2026-07-28T10:00:00Z",revision_token:"rev-1"};
const tasks=[
  {id:"task-1",template_version_id:"draft-1",code:"T001",sequence_no:1,title:"Confirm site",schedule_classification:"pre_activation",planned_start_day:null,planned_end_day:null,phase:"Activation",category:"Governance",applicability:"mandatory",validation_state:"valid",validation_issues:[]},
  {id:"task-2",template_version_id:"draft-1",code:"T002",sequence_no:2,title:"Start work",schedule_classification:"execution",planned_start_day:1,planned_end_day:1,phase:"Execution",category:"Site",applicability:"mandatory",validation_state:"valid",validation_issues:[]},
  {id:"task-3",template_version_id:"draft-1",code:"T003",sequence_no:3,title:"Inspect work",schedule_classification:"execution",planned_start_day:2,planned_end_day:2,phase:"Inspection",category:"Quality",applicability:"mandatory",validation_state:"valid",validation_issues:[]},
];
const dependency={id:"dep-1",template_version_id:"draft-1",predecessor_task_id:"task-1",successor_task_id:"task-2",dependency_type:"finish_to_start",blocking:true,rule_text:"Confirm site before starting",sequence_no:1,predecessor:{id:"task-1",code:"T001",title:"Confirm site"},successor:{id:"task-2",code:"T002",title:"Start work"},validation_state:"valid",validation_issues:[]};
const page=items=>({items,pagination:{page:1,page_size:100,total:items.length,total_pages:items.length?1:0},summary:{total:items.length,finish_to_start:items.filter(x=>x.dependency_type==="finish_to_start").length,start_to_start:items.filter(x=>x.dependency_type==="start_to_start").length,blocking:items.filter(x=>x.blocking).length,validation_issues:0}});

function view(role="super_admin", nextSummary=summary){return render(<TemplateDraftEditorEntry summary={nextSummary} user={{role}} onBack={vi.fn()}/>);}

beforeEach(()=>{
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page(tasks));
  templatesApi.listDependencies.mockResolvedValue(page([dependency]));
  templatesApi.listGates.mockResolvedValue(page([]));
  templatesApi.createDependency.mockResolvedValue({dependency:{...dependency,id:"dep-2",predecessor_task_id:"task-2",successor_task_id:"task-3",sequence_no:2},revision_token:"rev-2"});
  templatesApi.updateDependency.mockResolvedValue({dependency:{...dependency,dependency_type:"start_to_start"},revision_token:"rev-2"});
  templatesApi.deleteDependency.mockResolvedValue({dependency_id:"dep-1",deleted:true,revision_token:"rev-2"});
});

async function openDependencies(){
  view();
  await screen.findByTestId("draft-task-T001");
  fireEvent.click(screen.getByRole("button",{name:/dependencies \(1\)/i}));
  return screen.findByTestId("draft-dependency-dep-1");
}

describe("draft dependency authoring",()=>{
  it("loads the draft aggregate once without duplicate frontend requests",async()=>{
    await openDependencies();
    expect(templatesApi.getVersion).toHaveBeenCalledTimes(1);
    expect(templatesApi.listTasks).toHaveBeenCalledTimes(1);
    expect(templatesApi.listDependencies).toHaveBeenCalledTimes(1);
  });

  it("creates a relationship using only current draft task options",async()=>{
    await openDependencies();
    fireEvent.click(screen.getByRole("button",{name:/add relationship/i}));
    const dialog=screen.getByRole("dialog",{name:/add draft dependency/i});
    const predecessor=within(dialog).getByLabelText("Predecessor task");
    const successor=within(dialog).getByLabelText("Successor task");
    expect(within(predecessor).getAllByRole("option").map(o=>o.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("T001"),expect.stringContaining("T002"),expect.stringContaining("T003")]));
    fireEvent.change(predecessor,{target:{value:"task-2"}});
    expect(within(successor).getByRole("option",{name:/T002/})).toBeDisabled();
    fireEvent.change(successor,{target:{value:"task-3"}});
    fireEvent.change(within(dialog).getByLabelText("Dependency rule text"),{target:{value:"Start after execution begins"}});
    fireEvent.change(within(dialog).getByLabelText("Dependency sequence number"),{target:{value:"2"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/add relationship/i}));
    await waitFor(()=>expect(templatesApi.createDependency).toHaveBeenCalledWith("draft-1",expect.objectContaining({predecessor_task_id:"task-2",successor_task_id:"task-3",dependency_type:"finish_to_start",blocking:true,rule_text:"Start after execution begins",sequence_no:2,revision_token:"rev-1"})));
  });

  it("prevents the same task on both sides before calling the API",async()=>{
    await openDependencies();
    fireEvent.click(screen.getByRole("button",{name:/add relationship/i}));
    const dialog=screen.getByRole("dialog",{name:/add draft dependency/i});
    fireEvent.change(within(dialog).getByLabelText("Predecessor task"),{target:{value:"task-1"}});
    // Disabled options prevent normal same-task selection; force the state through a crafted change event.
    fireEvent.change(within(dialog).getByLabelText("Successor task"),{target:{value:"task-1"}});
    fireEvent.change(within(dialog).getByLabelText("Dependency rule text"),{target:{value:"Invalid self edge"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/add relationship/i}));
    expect(await within(dialog).findByText(/must be different tasks/i)).toBeInTheDocument();
    expect(templatesApi.createDependency).not.toHaveBeenCalled();
  });

  it("edits and deletes a relationship",async()=>{
    await openDependencies();
    fireEvent.click(screen.getByRole("button",{name:/edit dependency 1/i}));
    const dialog=screen.getByRole("dialog",{name:/edit draft dependency/i});
    fireEvent.change(within(dialog).getByLabelText("Dependency type"),{target:{value:"start_to_start"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/save dependency/i}));
    await waitFor(()=>expect(templatesApi.updateDependency).toHaveBeenCalledWith("draft-1","dep-1",expect.objectContaining({dependency_type:"start_to_start",revision_token:"rev-1"})));

    await waitFor(()=>expect(screen.queryByRole("dialog",{name:/edit draft dependency/i})).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button",{name:/delete dependency 1/i}));
    const deleteDialog=screen.getByRole("dialog",{name:/delete dependency/i}); fireEvent.click(within(deleteDialog).getByRole("button",{name:/^delete dependency$/i}));
    await waitFor(()=>expect(templatesApi.deleteDependency).toHaveBeenCalledWith("draft-1","dep-1","rev-1"));
  });

  it.each([
    ["template_dependency_cycle","The dependency would create a cycle in the draft graph."],
    ["template_dependency_exists","The predecessor, successor and dependency type already exist."],
  ])("renders backend %s errors without repair",async(code,message)=>{
    templatesApi.createDependency.mockRejectedValue({status:409,details:{detail:{code,message}}});
    await openDependencies();
    fireEvent.click(screen.getByRole("button",{name:/add relationship/i}));
    const dialog=screen.getByRole("dialog",{name:/add draft dependency/i});
    fireEvent.change(within(dialog).getByLabelText("Predecessor task"),{target:{value:"task-2"}});
    fireEvent.change(within(dialog).getByLabelText("Successor task"),{target:{value:"task-3"}});
    fireEvent.change(within(dialog).getByLabelText("Dependency rule text"),{target:{value:"Test relationship"}});
    fireEvent.change(within(dialog).getByLabelText("Dependency sequence number"),{target:{value:"2"}});
    fireEvent.click(within(dialog).getByRole("button",{name:/add relationship/i}));
    expect(await within(dialog).findByText(message)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button",{name:/repair/i})).not.toBeInTheDocument();
  });

  it("keeps published and non-Super-Admin versions immutable",async()=>{
    const published={...summary,status:"published",version_id:"published-1"};
    templatesApi.getVersion.mockResolvedValue(published);
    view("super_admin",published);
    expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button",{name:/add relationship/i})).not.toBeInTheDocument();

    cleanup();
    templatesApi.getVersion.mockResolvedValue(summary);
    view("admin");
    expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
  });

  it("uses mobile-friendly full-width actions",async()=>{
    await openDependencies();
    const add=screen.getByRole("button",{name:/add relationship/i});
    expect(add).toHaveClass("w-full");
    fireEvent.click(add);
    const dialog=screen.getByRole("dialog",{name:/add draft dependency/i});
    expect(within(dialog).getByRole("button",{name:/add relationship/i})).toHaveClass("w-full");
  });
});
