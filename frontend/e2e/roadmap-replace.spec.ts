import { expect, test } from "playwright/test";
import {
  approvedAnalysis,
  approveRoadmap,
  roadmap,
  startTicket,
  ticketRow,
} from "./published-plan";
import { login, openPlanDocument, showTab } from "./support";

test.describe("a RoadMap written again", () => {
  test("replaces the earlier plan's untouched Tickets and keeps the started one", async ({
    page,
  }) => {
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Replace plan");

    // The first plan is approved and its two Tickets are published.
    const first = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(first.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");
    await expect(ticketRow(page, "Write the mail")).toBeVisible();

    // Somebody starts one of them; the other stays untouched.
    await startTicket(page, "Send the link");

    // The RoadMap is written again with new Tickets and approved: the untouched Ticket of the
    // first plan is gone, the started one stays beside the new one.
    const second = await page.request.post(candidates, {
      headers,
      data: roadmap(["Confirm the address"]),
    });
    expect(second.status()).toBe(201);
    await approveRoadmap(page, "Confirm the address");
    await expect(ticketRow(page, "Confirm the address")).toBeVisible();
    await expect(ticketRow(page, "Send the link")).toBeVisible();
    await expect(ticketRow(page, "Write the mail")).toHaveCount(0);
  });

  test("a RoadMap reset takes every Ticket of the plan off the Kanban", async ({ page }) => {
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Reset plan");
    const plan = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(plan.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");
    await startTicket(page, "Send the link");

    // The reset says what it does to the Tickets before it does it.
    const roadmapDialog = await openPlanDocument(page, "RoadMap");
    await roadmapDialog.getByRole("button", { name: "Reset RoadMap" }).click();
    await expect(roadmapDialog.getByText(/Its 2 Tickets leave the Kanban/)).toBeVisible();
    await roadmapDialog.getByRole("button", { name: "Reset and clear" }).click();
    await expect(roadmapDialog.getByRole("button", { name: "Reset RoadMap" })).toHaveCount(0);

    // The untouched Ticket is deleted and the started one archived: neither is on the Kanban.
    await showTab(page, "Kanban");
    await expect(page.getByRole("region", { name: /^Column / }).first()).toBeVisible();
    await expect(ticketRow(page, "Write the mail")).toHaveCount(0);
    await expect(ticketRow(page, "Send the link")).toHaveCount(0);
  });
});
