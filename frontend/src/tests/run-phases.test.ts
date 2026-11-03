import { describe, expect, it } from "vitest";
import { failedStepKey, runFailureJson, runSteps } from "@/lib/runPhases";

describe("run steps", () => {
  it("shows the first step as active before the server recorded a phase", () => {
    const steps = runSteps("analysis", { status: "running", phase: "reading_info" });
    expect(steps.map((step) => step.state)).toEqual(["active", "pending", "pending"]);
  });

  it("marks earlier steps done and the reached step active", () => {
    const steps = runSteps("analysis", { status: "running", phase: "generating" });
    expect(steps.map((step) => step.state)).toEqual(["done", "done", "active"]);
    expect(steps[2].label).toBe("Generating analysis");
    expect(runSteps("roadmap", { status: "running", phase: "generating" })[2].label).toBe(
      "Generating RoadMap",
    );
  });

  it("finishes every step on a completed run", () => {
    const steps = runSteps("analysis", { status: "completed", phase: "generating" });
    expect(steps.map((step) => step.state)).toEqual(["done", "done", "done"]);
  });

  it("fails the step the run died on, not the last one", () => {
    const steps = runSteps("roadmap", { status: "failed", phase: "analysing_repository" });
    expect(steps.map((step) => step.state)).toEqual(["done", "failed", "pending"]);
    expect(failedStepKey({ status: "failed", phase: "analysing_repository" })).toBe(
      "analysing_repository",
    );
  });

  it("has no failure json unless the run failed", () => {
    expect(runFailureJson({ status: "running", phase: "generating", error_code: null, error_message: null })).toBeNull();
    const json = runFailureJson({
      status: "failed",
      phase: "generating",
      error_code: "provider_error",
      error_message: "The provider call failed: HTTP 400 model not found",
    });
    expect(JSON.parse(String(json))).toEqual({
      status: "failed",
      phase: "generating",
      error_code: "provider_error",
      error_message: "The provider call failed: HTTP 400 model not found",
    });
  });

  it("points at the first step when a run failed before recording one", () => {
    const steps = runSteps("analysis", { status: "failed", phase: null });
    expect(steps[0].state).toBe("failed");
    expect(failedStepKey({ status: "failed", phase: null })).toBe("reading_info");
  });
});
