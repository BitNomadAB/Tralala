# 0018 — An A2A agent is executed, not just tested

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** Agent connections and their connection test (`services/connections.py`), the run
  runtime (`services/runtime.py`), Loop generation and discussion rounds

## Problem

An agent could be configured with `connection_type: a2a`, the connection test fetched its Agent Card
and reported "connected", and then every run failed: `call_completion` unconditionally posted an
OpenAI-style body to `{base_url}/chat/completions`. The product therefore advertised a transport it
could not use, and the failure appeared as an opaque HTTP error inside a generation run.

## Decision

1. **`call_completion` dispatches on `connection_type`.** OpenAI-compatible agents keep the existing
   path; `a2a` agents go to `call_a2a`.
2. **`call_a2a` speaks the protocol.** It fetches the Agent Card (`base_url/.well-known/agent.json`,
   or the base URL itself when it already ends in `.json`), uses the card's `url` when present as the
   RPC endpoint, and sends one JSON-RPC 2.0 `message/send` with `configuration.blocking = true`.
3. **The transcript is one text part.** A2A has no system role, so the role prompt and the exchange
   are joined into a single `text` part with `[instructions]` / `[user]` / `[assistant]` markers. That
   is lossy but portable; a future A2A `contextId` conversation can replace it without touching the
   callers.
4. **The answer is collected, not assumed.** Text comes from `result.parts`, then
   `result.artifacts[].parts`, then `result.status.message.parts`. A JSON-RPC `error` is reported as
   `a2a:<code>`, and a result with no text is `a2a_empty_response` — a failed run says why.
5. **The failure shape is unchanged.** `call_a2a` returns the same `{ok, error, text, model, usage}`
   dict as the OpenAI path, so generation, discussion and QA need no branch of their own.

## Consequences

- An A2A agent now produces Loop candidates and discussion answers. The card test keeps its meaning:
  it answers "can I reach the agent", not "will a run work", and both are now true for a healthy
  agent.
- Card fetching happens on every call. Runs are seconds-long and infrequent; caching a card would add
  an invalidation problem for no measurable gain. If that changes, the card call is one place.
- `model` is reported as the agent's configured model or `a2a`, because the protocol has no model
  concept; usage stays empty, so token budgets in a run see zero rather than a guess.
- Streaming A2A (`message/stream`) is not used: the runtime is synchronous by design, and the
  generation and discussion callers are built around a complete answer.

## Alternatives considered

- **Reject `a2a` at agent creation until it is implemented.** Honest, but it removes the connection
  test that already worked and gives an operator nothing to configure.
- **Keep the OpenAI shape and let A2A agents fail.** What the product did before this decision; it
  reports a broken integration as a provider error and wastes an operator's afternoon.
- **Implement streaming and task resumption now.** More protocol, more state, no caller that needs
  it. The synchronous `message/send` covers every current use.
