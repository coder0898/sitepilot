import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDetails } from "./TemplateDetails";

vi.mock("../../api/templatesApi", () => ({
  templatesApi: { getVersion: vi.fn(), listTasks: vi.fn(), listDependencies: vi.fn(), listGates: vi.fn(), list: vi.fn() },
}));

const summary = { template_id:"template-1", template_code:"WORKVED-45", template_name:"Workved 45-Day Permanent Task Template", template_description:"Approved", version_id:"version-1", version_no:1, status:"published", is_current_published:true, duration_days:45, task_count:99, dependency_count:38, gate_count:32, created_at:"2026-07-24T10:00:00Z", published_at:"2026-07-27T10:00:00Z" };
const task = code => ({ id:`id-${code}`, code, title:`Task ${code}`, phase:"Site Setup", day:1 });
const exactGate = { id:"g1", code:"E001", sequence_no:1, approval_name:"Society work permission", description:"Approval", external_party:"Society", required_by_type:"source_text", required_by_value:"Before Day 1", impact:"Blocks mobilisation", mapping_classification:"exact", requires_configuration:false, broad_mapping_text:null, affected_tasks:[task("T008")], validation_state:"valid", validation_issues:[] };
const broadGate = { id:"g6", code:"E006", sequence_no:6, approval_name:"General execution approval", description:null, external_party:"Client", required_by_type:"source_text", required_by_value:"T008 onwards", impact:"Affected execution", mapping_classification:"broad_text", requires_configuration:true, broad_mapping_text:"T008 onwards", affected_tasks:[], validation_state:"valid", validation_issues:[] };
const gates = [exactGate, broadGate, ...Array.from({length:30}, (_,i)=>({ ...exactGate, id:`gx${i}`, code:`E${String(i+3).padStart(3,"0")}`, sequence_no:i+3, affected_tasks:[task(`T${String(i+9).padStart(3,"0")}`)] }))];
const gateResponse = (items=gates,total=32) => ({ items, pagination:{page:1,page_size:100,total,total_pages:total?1:0} });
const taskResponse = { items:[{id:"id-T008",code:"T008",sequence_no:8,title:"Task T008",description:"",schedule_classification:"execution",planned_start_day:1,planned_end_day:1,phase:"Site Setup",category:"Setup",applicability:"mandatory",task_class:null,task_kind:null,evidence_required:null,duration_days:null,validation_state:"valid",validation_issues:[]}], pagination:{page:1,page_size:20,total:1,total_pages:1} };

function Harness({ role="admin" }) { const [tab,setTab]=useState("gates"); return <TemplateDetails versionId="version-1" user={{role}} onBack={vi.fn()} activeTemplateTab={tab} onTabChange={setTab} debounceMs={0}/>; }

beforeEach(()=>{ vi.clearAllMocks(); templatesApi.getVersion.mockResolvedValue(summary); templatesApi.listTasks.mockResolvedValue(taskResponse); templatesApi.listDependencies.mockResolvedValue({items:[],pagination:{page:1,page_size:100,total:0,total_pages:0},summary:{total:0,finish_to_start:0,start_to_start:0,blocking:0,validation_issues:0}}); templatesApi.listGates.mockResolvedValue(gateResponse()); });

describe("External Gates review",()=>{
  it("renders 32 gates, exact mappings, broad text and configuration warning", async()=>{
    render(<Harness/>);
    expect(await screen.findByRole("heading", { name: "External gates" }, {timeout:3000})).toBeInTheDocument();
    const metrics=screen.getByLabelText("External gate summary");
    expect(within(metrics).getByText("32")).toBeInTheDocument();
    expect(screen.getAllByText("E001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("E006").length).toBeGreaterThan(0);
    fireEvent.click(within(screen.getByTestId("gate-card-g6")).getByText("View gate details"));
    expect(screen.getAllByText("T008 onwards").length).toBeGreaterThan(0);
    expect(within(screen.getByTestId("gate-card-g6")).getByText(/No mapping has been assumed/i)).toBeInTheDocument();
    expect(screen.queryByText(/External gates arrive/i)).not.toBeInTheDocument();
  });

  it("sends all supported filters and clears them", async()=>{
    render(<Harness/>); await screen.findByRole("heading", { name: "External gates" });
    fireEvent.change(screen.getByLabelText("Search external gates"),{target:{value:" E006 "}});
    fireEvent.change(screen.getByLabelText("Filter gate mapping"),{target:{value:"broad_text"}});
    fireEvent.change(screen.getByLabelText("Filter gate configuration"),{target:{value:"true"}});
    fireEvent.change(screen.getByLabelText("Filter external party"),{target:{value:" Client "}});
    fireEvent.change(screen.getByLabelText("Filter gate validation"),{target:{value:"valid"}});
    await waitFor(()=>expect(templatesApi.listGates.mock.calls.at(-1)[1]).toEqual({page:1,page_size:100,search:"E006",mapping_classification:"broad_text",requires_configuration:true,external_party:"Client",validation_state:"valid"}));
    fireEvent.click(screen.getByRole("button",{name:/clear/i}));
    await waitFor(()=>expect(templatesApi.listGates.mock.calls.at(-1)[1]).toEqual({page:1,page_size:100}));
  }, 10000);

  it("shows invalid gate warnings and retryable authorization errors", async()=>{
    templatesApi.listGates.mockResolvedValueOnce(gateResponse([{...exactGate,id:"bad",validation_state:"invalid",validation_issues:["cross_version_mapping"]}],1));
    render(<Harness/>);
    expect(await screen.findByText(/1 gate require review/i)).toBeInTheDocument();
    expect(screen.getByTestId("gate-card-bad")).toHaveTextContent("cross version mapping");
  });

  it("opens exact mapped tasks in Tasks without losing the version", async()=>{
    render(<Harness/>); await screen.findByRole("heading", { name: "External gates" });
    fireEvent.click(within(screen.getByTestId("gate-card-g1")).getByText("View gate details"));
    fireEvent.click(within(screen.getByTestId("gate-card-g1")).getByTitle("Open T008 in Tasks"));
    expect(await screen.findByLabelText("Search template tasks")).toHaveValue("T008");
    await waitFor(()=>expect(templatesApi.listTasks.mock.calls.at(-1)[0]).toBe("version-1"));
  });
});
