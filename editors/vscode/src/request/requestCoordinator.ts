import * as vscode from "vscode";

import type { AgentProvider } from "../agent/agentProvider";
import type { SemanticSelectionService } from "../editor/semanticSelection";
import type { ReviewNavigator } from "../review/reviewNavigator";

const MAX_TRANSCRIPT_CHARACTERS = 10_000;

export class RequestCoordinator {
  private transcript: string | undefined;

  public constructor(
    private readonly selection: SemanticSelectionService,
    private readonly review: ReviewNavigator,
    private readonly agent: AgentProvider,
    private readonly output: vscode.OutputChannel,
    private readonly status: (message: string) => void,
  ) {}

  public preview(transcript: string): void {
    const normalized = transcript.trim();
    if (normalized.length === 0) {
      throw new Error("The transcribed request is empty");
    }
    if (normalized.length > MAX_TRANSCRIPT_CHARACTERS) {
      throw new Error(
        `The transcribed request exceeds ${MAX_TRANSCRIPT_CHARACTERS} characters`,
      );
    }
    this.transcript = normalized;
    const summary =
      normalized.length > 160 ? `${normalized.slice(0, 157)}...` : normalized;
    this.output.appendLine(
      `Voice request previewed (${normalized.length} characters).`,
    );
    this.status("Voice request ready; confirm or cancel with a gesture");
    void vscode.window.showInformationMessage(`Chudvis request: ${summary}`);
  }

  public async submit(): Promise<void> {
    const transcript = this.consume();
    const selection = this.selection.context();
    this.review.beginSession();
    await this.agent.submit({ transcript, selection });
    this.transcript = undefined;
    this.status(
      "Agent request submitted; changed files will appear in the review stack",
    );
  }

  public consume(): string {
    const transcript = this.transcript;
    if (transcript === undefined) {
      throw new Error("There is no pending voice request to submit");
    }
    this.transcript = undefined;
    return transcript;
  }

  public cancel(): void {
    if (this.transcript !== undefined) {
      this.output.appendLine("Pending voice request cancelled.");
    }
    this.transcript = undefined;
    this.status("Pending request cancelled");
  }
}
