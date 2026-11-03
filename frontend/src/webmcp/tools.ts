/**
 * The WebMCP tool catalogue: one module per page that registers tools. Every `execute` calls the
 * same REST client as the UI.
 */
export { cardTools } from "./cardTools";
export { dashboardTools } from "./dashboardTools";
export { loopTools, type LoopColumn } from "./loopTools";
export type { McpTool } from "./toolSchema";
