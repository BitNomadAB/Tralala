/**
 * The API's response shapes, one module per domain. Import from `@/lib/types`, not from a
 * domain module, so a type can move between domains without touching its users.
 */
export * from "./account";
export * from "./board";
export type * from "./agent";
export type * from "./loop";
export type * from "./card";
export type * from "./discussion";
