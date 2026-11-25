import { Chip } from "@/components/ui/chip";

/**
 * The mark of a Loop that runs its Tickets without a plan (`without_plan`), beside its stage
 * wherever the Loop is shown: its header, its row on the board page and its row under "Waits for
 * you". It is said in words, so planned and unplanned work are never told apart by colour alone.
 */
export function WithoutPlanChip() {
  return <Chip>Without a plan</Chip>;
}
