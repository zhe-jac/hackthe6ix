import assert from "node:assert/strict";
import test from "node:test";

import {
  invalidEditProposalResult,
  planEditToolRound,
  unhandledEditToolCalls,
} from "../model/editToolRound";

const proposal = {
  id: "proposal-1",
  name: "propose_edits",
  argumentsValue: { edits: [] },
};

void test("a lone proposal finishes the tool-gathering phase", () => {
  assert.deepEqual(planEditToolRound([proposal]), {
    kind: "proposal",
    call: proposal,
  });
});

void test("a proposal mixed with reads is rejected while every call gets an output", () => {
  const read = {
    id: "read-1",
    name: "read_workspace_file",
    argumentsValue: { path: "test.py" },
  };

  const plan = planEditToolRound([read, proposal]);

  assert.equal(plan.kind, "execute");
  assert.equal(plan.calls.length, 2);
  assert.deepEqual(plan.calls[0], { call: read });
  const plannedProposal = plan.calls[1];
  assert(plannedProposal !== undefined);
  assert.deepEqual(plannedProposal.call, proposal);
  assert.deepEqual(plannedProposal.fixedResult, {
    success: false,
    accepted: false,
    retryable: true,
    error:
      "propose_edits must be called alone after all read-only tool results are available. Use the parallel read results, then call propose_edits alone in the next round.",
  });
});

void test("cumulative Backboard responses process each tool-call ID once", () => {
  const read = {
    id: "read-1",
    name: "read_workspace_file",
    argumentsValue: { path: "test.py" },
  };
  const handled = new Set([read.id]);

  const pending = unhandledEditToolCalls([read, proposal], handled);

  assert.deepEqual(pending, [proposal]);
  assert.deepEqual(planEditToolRound(pending), {
    kind: "proposal",
    call: proposal,
  });
});

void test("invalid proposals produce a bounded retry result", () => {
  assert.deepEqual(
    invalidEditProposalResult(new Error("edit 1 replacementText is invalid")),
    {
      success: false,
      accepted: false,
      retryable: true,
      error:
        "Invalid propose_edits arguments: edit 1 replacementText is invalid. Retry propose_edits alone with every path, originalText, replacementText, and reason encoded as strings.",
    },
  );
});
