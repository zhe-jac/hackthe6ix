export type VoiceRoute =
  | { readonly kind: "open"; readonly query: string }
  | { readonly kind: "symbol"; readonly query: string }
  | { readonly kind: "references"; readonly query: string | undefined }
  | { readonly kind: "undo" }
  | { readonly kind: "cancel" }
  | { readonly kind: "question"; readonly instruction: string }
  | { readonly kind: "edit"; readonly instruction: string };

const QUESTION_PREFIX =
  /^(?:please\s+)?(?:explain|analy[sz]e|why|what|how)\b/iu;
const MUTATION_VERB = /\b(?:change|fix|add|remove|rename|refactor)\b/iu;

export function routeVoiceRequest(transcript: string): VoiceRoute {
  const instruction = transcript.trim().replace(/\s+/gu, " ");
  if (instruction.length === 0) {
    throw new Error("Voice request is empty");
  }

  let match = /^(?:please\s+)?open(?:\s+file)?\s+(.+)$/iu.exec(instruction);
  if (match?.[1] !== undefined) {
    return { kind: "open", query: match[1].trim() };
  }
  match =
    /^(?:please\s+)?go\s+to(?:\s+(?:function|class|symbol))?\s+(.+)$/iu.exec(
      instruction,
    );
  if (match?.[1] !== undefined) {
    return { kind: "symbol", query: match[1].trim() };
  }
  match = /^(?:please\s+)?show\s+references(?:\s+(?:to\s+)?(.+))?$/iu.exec(
    instruction,
  );
  if (match !== null) {
    const query = match[1]?.trim();
    return {
      kind: "references",
      query: query === undefined || /^this$/iu.test(query) ? undefined : query,
    };
  }
  if (/^(?:please\s+)?undo(?:\s+(?:that|last\s+edit))?$/iu.test(instruction)) {
    return { kind: "undo" };
  }
  if (/^(?:please\s+)?(?:cancel|never\s+mind)$/iu.test(instruction)) {
    return { kind: "cancel" };
  }
  if (QUESTION_PREFIX.test(instruction)) {
    return { kind: "question", instruction };
  }
  if (MUTATION_VERB.test(instruction)) {
    return { kind: "edit", instruction };
  }
  return { kind: "question", instruction };
}
