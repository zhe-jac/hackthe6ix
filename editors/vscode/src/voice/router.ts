import { isSupportedCreateFilePath, requestedFilePath } from "./fileIntent";

export type VoiceRoute =
  | { readonly kind: "open"; readonly query: string }
  | { readonly kind: "create"; readonly path: string }
  | { readonly kind: "symbol"; readonly query: string }
  | { readonly kind: "references"; readonly query: string | undefined }
  | { readonly kind: "undo" }
  | { readonly kind: "cancel" }
  | { readonly kind: "question"; readonly instruction: string }
  | { readonly kind: "edit"; readonly instruction: string }
  | { readonly kind: "unsupported"; readonly instruction: string };

const QUESTION_PREFIX =
  /^(?:please\s+)?(?:explain|analy[sz]e|why|what|how|describe|summarize|tell\s+me)\b/iu;
const MUTATION_VERB =
  /\b(?:add|change|convert|create|delete|extract|fix|implement|insert|make|modify|move|refactor|remove|rename|replace|set|update|write)\b/iu;

export function routeVoiceRequest(transcript: string): VoiceRoute {
  const instruction = transcript.trim().replace(/\s+/gu, " ");
  if (instruction.length === 0) {
    throw new Error("Voice request is empty");
  }

  let match =
    /^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?open(?:\s+file)?\s+(.+)$/iu.exec(
      instruction,
    );
  if (match?.[1] !== undefined) {
    return { kind: "open", query: match[1].trim() };
  }
  match =
    /^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?(?:create|generate|make)(?:\s+me)?\s+(?:(?:a|the)\s+)?(?:new\s+)?(?:(markdown|python|typescript|javascript|text|json|ya?ml|html|css)\s+)?(?:file|script)(?:\s+(?:named|called))?\s+(.+)$/iu.exec(
      instruction,
    );
  if (match?.[2] !== undefined) {
    return {
      kind: "create",
      path: requestedFilePath(match[1], match[2]),
    };
  }
  match =
    /^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?(?:create|generate|make)(?:\s+me)?\s+(.+)$/iu.exec(
      instruction,
    );
  if (match?.[1] !== undefined && isSupportedCreateFilePath(match[1])) {
    return {
      kind: "create",
      path: requestedFilePath(undefined, match[1]),
    };
  }
  match =
    /^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?go\s+to(?:\s+(?:function|class|symbol))?\s+(.+)$/iu.exec(
      instruction,
    );
  if (match?.[1] !== undefined) {
    return { kind: "symbol", query: match[1].trim() };
  }
  match =
    /^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?show\s+references(?:\s+(?:to\s+)?(.+))?$/iu.exec(
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
  return { kind: "unsupported", instruction };
}
