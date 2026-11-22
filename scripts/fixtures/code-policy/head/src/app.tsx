"use strict";

// moved block comment: the block moves up
export const movedSmall = "moved";

/**
 * Existing doc comment above an export.
 */
export function useExisting(): number {
  return 1;
}

// a newly added line comment
export function added(): string {
  const note = "a // separator inside a string";
  const url = "https://example.invalid/path?query=1";
  useEffect(() => {
    return () => {};
  });
  React.useEffect(() => {
    return () => {};
  });
  // eslint-disable-next-line no-new-comment
  return note + url;
}

// existing comment kept in place
export function keep(): string {
  const existing = "https://example.invalid/a";
  useEffect(() => {
    return () => {};
  });
  return existing;
}
