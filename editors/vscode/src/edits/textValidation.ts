export interface OffsetRange {
  readonly startOffset: number;
  readonly endOffset: number;
}

export function uniqueTextRange(
  text: string,
  originalText: string,
): OffsetRange {
  if (originalText.length === 0) {
    if (text.length === 0) {
      return { startOffset: 0, endOffset: 0 };
    }
    throw new Error("empty originalText is valid only for an empty file");
  }
  const startOffset = text.indexOf(originalText);
  if (startOffset < 0 || text.slice(startOffset + 1).includes(originalText)) {
    throw new Error("originalText must occur exactly once");
  }
  return { startOffset, endOffset: startOffset + originalText.length };
}

export function assertNonOverlapping(
  ranges: readonly OffsetRange[],
  label: string,
): void {
  const sorted = [...ranges].sort(
    (left, right) => left.startOffset - right.startOffset,
  );
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    if (
      previous !== undefined &&
      current !== undefined &&
      (previous.endOffset > current.startOffset ||
        (previous.startOffset === previous.endOffset &&
          current.startOffset === current.endOffset &&
          previous.startOffset === current.startOffset))
    ) {
      throw new Error(`Proposed edits overlap in '${label}'`);
    }
  }
}

export function matchesUndoGuard(
  currentText: string,
  currentVersion: number,
  appliedText: string,
  appliedVersion: number,
): boolean {
  return currentVersion === appliedVersion && currentText === appliedText;
}
