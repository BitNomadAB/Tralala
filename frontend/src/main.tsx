import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/App";
import { reportCaughtError } from "@/app/errorReporting";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing");

createRoot(root, { onCaughtError: reportCaughtError }).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
