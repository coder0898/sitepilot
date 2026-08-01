import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProjectDependencies } from "./components/ProjectDependencies";
import { projectsApi } from "../../api/projectsApi";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { dependencies: vi.fn(), generateDependencies: vi.fn() } }));
const project={id:"p1",status:"draft"}; const user={role:"admin"};

describe("ProjectDependencies",()=>{
  it("generates once, renders count and excluded-task warnings",async()=>{
    projectsApi.dependencies.mockResolvedValueOnce({total:0,excluded_warning_count:0,items:[]}).mockResolvedValueOnce({total:38,excluded_warning_count:1,items:[{id:"d1",sequence:1,dependency_type:"finish_to_start",blocking:true,rule_text:"Rule",predecessor_code:"T001",predecessor_title:"A",predecessor_included:true,successor_code:"T002",successor_title:"B",successor_included:false,excluded_task_warning:true,source:"template"}]});
    projectsApi.generateDependencies.mockResolvedValue({generated_dependency_count:38,no_op:false});
    render(<ProjectDependencies project={project} user={user}/>);
    await screen.findByText("No project dependencies generated");
    fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button",{name:/generate dependencies/i}));
    await waitFor(()=>expect(projectsApi.generateDependencies).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("38 dependencies")).toBeInTheDocument();
    expect(screen.getByText(/includes an excluded task/i)).toBeInTheDocument();
  });
  it("uses full-width mobile generation action",async()=>{
    projectsApi.dependencies.mockResolvedValue({total:0,excluded_warning_count:0,items:[]});
    render(<ProjectDependencies project={project} user={user}/>);
    expect(await screen.findByRole("button",{name:/generate dependencies/i})).toHaveClass("w-full");
  });
});
