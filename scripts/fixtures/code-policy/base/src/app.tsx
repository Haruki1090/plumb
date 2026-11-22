"use strict";

/**
 * Existing doc comment above an export.
 */
export function useExisting(): number {
  return 1;
}

// moved block comment: the block moves up
export const movedSmall = "moved";

// existing comment kept in place
export function keep(): string {
  const existing = "https://example.invalid/a";
  useEffect(() => {
    return () => {};
  });
  return existing;
}
