import http from "node:http";

/**
 * A stand-in OpenAI-compatible model for the generation journeys: it answers slowly, so the
 * intermediate steps of a run are visible, fails for one model and calls the connection test's
 * dummy tool for another, as a model that takes tools does. Every chat request is recorded, so a
 * journey can say what the server sent the model.
 */
export const PORT = 8098;
export const SLOW_MODEL = "slow-model";
export const BROKEN_MODEL = "broken-model";
// Slow enough to leave the Info tab, edit and save while the run is still working.
export const PATIENT_MODEL = "patient-model";
// Calls the connection test's dummy tool, so the agent is recorded as reading with tools.
export const TOOL_MODEL = "tool-model";

export const ANALYSIS = {
  schema_version: 1,
  outcome: "Expire idle sessions",
  scope: ["idle timeout"],
  findings: [
    {
      id: "F-01",
      title: "The session table has no expiry column",
      category: "change",
      technical_detail: "backend/app/services/auth.py",
      plain_language: "Sessions never time out today.",
    },
  ],
  assumptions: [],
  open_questions: [],
  options: [],
  recommendation: "Add an expiry column.",
  verification: ["An idle session is rejected"],
  sources: [],
  repository_revision: "",
};

/** The brief for people of ANALYSIS: its only finding is a change, so no finding must be named. */
export const ANALYSIS_BRIEF = {
  schema_version: 1,
  obstacles: [],
  pros: [{ text: "Idle sessions end by themselves.", finding_ids: ["F-01"] }],
  cons: [],
  decisions: [],
  size: { kind: "small", text: "One check is added where sessions are read." },
  verdict: "yes",
  verdict_line: "Yes: idle sessions can end by themselves.",
  verdict_reason: "Nothing stands in the way.",
  summary: "Sessions that nobody uses end after a while.",
  recommendation: "Go ahead.",
};

interface ChatMessage {
  content?: unknown;
}

/** The brief for people of a RoadMap: its goal in one line; the page counts the Tickets. */
const ROADMAP_BRIEF = { schema_version: 2, goal: "The plan is done and its Tickets are complete." };

/** The brief a request for people asks for, or null for any other request. */
function briefFor(messages: unknown): unknown {
  const texts = (Array.isArray(messages) ? (messages as ChatMessage[]) : []).map((message) =>
    typeof message.content === "string" ? message.content : "",
  );
  const roadmap = texts.find((content) => content.includes("Technical RoadMap (JSON):"));
  if (roadmap) return ROADMAP_BRIEF;
  return texts.some((content) => content.includes("Technical analysis (JSON):"))
    ? ANALYSIS_BRIEF
    : null;
}

/**
 * One chat request: the model, the tools it was offered, whether it asked for an analysis, and the
 * brief for people it asked for (null when it asked for none).
 */
export interface Received {
  model: string;
  tools: string[];
  analysis: boolean;
  brief: unknown;
}

export const received: Received[] = [];

function read(body: string): Received {
  try {
    const parsed = JSON.parse(body || "{}") as {
      model?: unknown;
      tools?: { function?: { name?: string } }[];
      messages?: unknown;
    };
    return {
      model: String(parsed.model ?? ""),
      tools: (parsed.tools ?? []).map((tool) => tool.function?.name ?? ""),
      analysis: JSON.stringify(parsed.messages ?? []).includes("Purpose: analysis"),
      brief: briefFor(parsed.messages),
    };
  } catch {
    return { model: "", tools: [], analysis: false, brief: null };
  }
}

function json(response: http.ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

const TOOL_CALL = {
  choices: [
    {
      message: {
        content: null,
        tool_calls: [
          { id: "call_1", type: "function", function: { name: "report_ok", arguments: "{}" } },
        ],
      },
    },
  ],
};

function answer(response: http.ServerResponse, request: Received) {
  if (request.tools.includes("report_ok")) {
    json(response, 200, TOOL_CALL);
    return;
  }
  if (request.model === BROKEN_MODEL) {
    json(response, 400, { error: { message: "Model Not Exist" } });
    return;
  }
  const content = "```json\n" + JSON.stringify(request.brief ?? ANALYSIS) + "\n```";
  setTimeout(
    () => json(response, 200, { choices: [{ message: { content } }], usage: { total_tokens: 21 } }),
    request.model === PATIENT_MODEL ? 6000 : 2500,
  );
}

export async function startStandInModel(): Promise<http.Server> {
  const server = http.createServer((request, response) => {
    const url = request.url ?? "";
    if (request.method === "GET" && url.endsWith("/models")) {
      json(response, 200, { data: [SLOW_MODEL, TOOL_MODEL].map((id) => ({ id })) });
      return;
    }
    if (request.method === "POST" && url.endsWith("/chat/completions")) {
      let body = "";
      request.on("data", (chunk) => (body += chunk));
      request.on("end", () => {
        const seen = read(body);
        received.push(seen);
        answer(response, seen);
      });
      return;
    }
    json(response, 404, { error: { message: "not found" } });
  });
  await new Promise<void>((resolve) => server.listen(PORT, "127.0.0.1", () => resolve()));
  return server;
}

export async function stopStandInModel(server: http.Server | null): Promise<void> {
  await new Promise<void>((resolve) => {
    if (!server) return resolve();
    server.close(() => resolve());
  });
}
