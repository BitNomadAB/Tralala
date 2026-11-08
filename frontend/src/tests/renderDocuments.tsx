import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { ToastProvider } from "@/components/ui/toast";
import { LoopDocumentsPanel } from "@/features/loops/LoopDocumentsPanel";
import type { PlanTab } from "@/features/loops/loopUi";
import { BOARD_ID, LOOP } from "./msw/loops";

/**
 * The planning documents of the Plan tab for a person, opened on `initialTab`, against whatever
 * handlers the test installed. The open document changes as the page changes it (the page keeps it
 * in the URL): a tab press renders the panel on the new document. Returns the query client, so a
 * test can wait for what it loaded.
 */
export function renderDocuments(initialTab: PlanTab): QueryClient {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let rerender: ((next: ReactElement) => void) | null = null;
  const ui = (tab: PlanTab): ReactElement => (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <LoopDocumentsPanel
          boardId={BOARD_ID}
          loop={LOOP}
          tab={tab}
          onTabChange={(next) => rerender?.(ui(next))}
          isHuman
          readOnly={false}
          onChanged={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>
  );
  rerender = render(ui(initialTab)).rerender;
  return queryClient;
}
