import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/App";
import { watchStaleChunks } from "@/app/chunkLoading";
import { reportCaughtError } from "@/app/errorReporting";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing");

// Before the first render, so the first page's chunk is already covered.
watchStaleChunks();

createRoot(root, { onCaughtError: reportCaughtError }).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
