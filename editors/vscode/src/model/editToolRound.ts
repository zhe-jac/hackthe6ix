export interface EditToolCall {
  readonly id: string;
  readonly name: string;
  readonly argumentsValue: unknown;
}

export interface ExecutableEditToolCall {
  readonly call: EditToolCall;
  readonly fixedResult?: Readonly<Record<string, unknown>>;
}

export type EditToolRoundPlan =
  | {
      readonly kind: "proposal";
      readonly call: EditToolCall;
    }
  | {
      readonly kind: "execute";
      readonly calls: readonly ExecutableEditToolCall[];
    };

export function unhandledEditToolCalls(
  calls: readonly EditToolCall[],
  handledCallIds: ReadonlySet<string>,
): readonly EditToolCall[] {
  return calls.filter((call) => !handledCallIds.has(call.id));
}

const MIXED_PROPOSAL_RESULT = {
  success: false,
  accepted: false,
  retryable: true,
  error:
    "propose_edits must be called alone after all read-only tool results are available. Use the parallel read results, then call propose_edits alone in the next round.",
} as const;

export function invalidEditProposalResult(
  error: unknown,
): Readonly<Record<string, unknown>> {
  const detail = error instanceof Error ? error.message : "invalid arguments";
  return {
    success: false,
    accepted: false,
    retryable: true,
    error: `Invalid propose_edits arguments: ${detail}. Retry propose_edits alone with every path, originalText, replacementText, and reason encoded as strings.`,
  };
}

export function planEditToolRound(
  calls: readonly EditToolCall[],
): EditToolRoundPlan {
  const proposalCalls = calls.filter((call) => call.name === "propose_edits");
  const proposal = proposalCalls[0];
  if (
    calls.length === 1 &&
    proposalCalls.length === 1 &&
    proposal !== undefined
  ) {
    return { kind: "proposal", call: proposal };
  }
  return {
    kind: "execute",
    calls: calls.map((call) =>
      call.name === "propose_edits"
        ? { call, fixedResult: MIXED_PROPOSAL_RESULT }
        : { call },
    ),
  };
}
