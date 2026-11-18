import { http } from "msw";
import type { BoardList, Card } from "@/lib/types";
import { isRecord, ticketCard } from "./cards";
import { apiPath, failure, ok, requestPath } from "./envelope";
import { LOOP_PATH } from "./loops";

/** The Loop's columns and cards as a small server keeps them, and every write sent to it. */
export interface KanbanServer {
  lists: BoardList[];
  cards: Card[];
  writes: { route: string; body: unknown }[];
}

/** The column's cards in their stored order. */
function inColumn(server: KanbanServer, listId: string): Card[] {
  return server.cards.filter((card) => card.list_id === listId);
}

/** Moves `card` to `position` among the other cards of `listId`, as the backend stores a move. */
function moveCard(server: KanbanServer, card: Card, listId: string, position: number): Card {
  const moved = { ...card, list_id: listId, version: card.version + 1 };
  const rest = server.cards.filter((item) => item.id !== card.id);
  const column = rest.filter((item) => item.list_id === listId);
  const before = column[position];
  const at = before ? rest.indexOf(before) : rest.length;
  rest.splice(at, 0, moved);
  server.cards = rest;
  return moved;
}

/**
 * Handlers for the Kanban's reads and writes over `server`: the columns, each column's cards, the
 * search, and the moves, renames, archives and new cards, each recorded in `server.writes`.
 */
export function kanbanHandlers(server: KanbanServer) {
  const record = async (request: Request) => {
    const body: unknown = await request.json().catch(() => null);
    server.writes.push({ route: `${request.method} ${requestPath(request)}`, body });
    return body;
  };
  return [
    http.get(apiPath(`${LOOP_PATH}/lists`), () => ok(server.lists)),
    http.get(apiPath(`${LOOP_PATH}/cards`), ({ request }) => {
      const listId = new URL(request.url).searchParams.get("list_id") ?? "";
      return ok(inColumn(server, listId));
    }),
    http.get(apiPath(`${LOOP_PATH}/search`), ({ request }) => {
      const words = (new URL(request.url).searchParams.get("q") ?? "").toLowerCase();
      return ok(server.cards.filter((card) => card.title.toLowerCase().includes(words)));
    }),
    http.post(apiPath(`${LOOP_PATH}/cards`), async ({ request }) => {
      const body = await record(request);
      if (!isRecord(body) || typeof body.list_id !== "string" || typeof body.title !== "string") {
        return failure(422, "validation_error", "Expected a column and a title");
      }
      const card = ticketCard({
        id: `card-${server.cards.length + 1}`,
        list_id: body.list_id,
        title: body.title,
        ticket_key: null,
        kind: "manual",
      });
      server.cards.push(card);
      return ok(card);
    }),
    http.post(apiPath(`${LOOP_PATH}/cards/:cardId/move`), async ({ request, params }) => {
      const body = await record(request);
      const card = server.cards.find((item) => item.id === params.cardId);
      if (!card || !isRecord(body) || typeof body.list_id !== "string") {
        return failure(404, "not_found", "No such card");
      }
      const position = typeof body.position === "number" ? body.position : 0;
      return ok(moveCard(server, card, body.list_id, position));
    }),
    http.post(apiPath(`${LOOP_PATH}/lists/:listId/move`), async ({ request, params }) => {
      const body = await record(request);
      const list = server.lists.find((item) => item.id === params.listId);
      if (!list || !isRecord(body) || typeof body.position !== "number") {
        return failure(404, "not_found", "No such column");
      }
      const rest = server.lists.filter((item) => item.id !== list.id);
      rest.splice(body.position, 0, list);
      server.lists = rest.map((item, position) => ({ ...item, position }));
      return ok(server.lists);
    }),
    http.post(apiPath(`${LOOP_PATH}/lists`), async ({ request }) => {
      const body = await record(request);
      const first = server.lists[0];
      if (!first || !isRecord(body) || typeof body.name !== "string") {
        return failure(422, "validation_error", "Expected a name");
      }
      const list = { ...first, id: `list-${server.lists.length + 1}`, name: body.name };
      server.lists = [...server.lists, { ...list, position: server.lists.length }];
      return ok(list);
    }),
    http.patch(apiPath(`${LOOP_PATH}/lists/:listId`), async ({ request, params }) => {
      const body = await record(request);
      const name = isRecord(body) && typeof body.name === "string" ? body.name : "";
      server.lists = server.lists.map((item) =>
        item.id === params.listId ? { ...item, name } : item,
      );
      return ok(server.lists.find((item) => item.id === params.listId));
    }),
    http.post(apiPath(`${LOOP_PATH}/lists/:listId/archive`), async ({ request, params }) => {
      await record(request);
      const list = server.lists.find((item) => item.id === params.listId);
      server.lists = server.lists.filter((item) => item.id !== params.listId);
      return ok(list);
    }),
  ];
}
