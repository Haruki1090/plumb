// SPDX-License-Identifier: MIT
// an ordinary leading comment
export const headerExample = 1;
/**
 * A doc comment directly above an export.
 */
export function docExport(): number {
  // prettier-ignore
  return 2;
}
/* prettier-ignore */
export const ignored = 3;
/** Export docs */ // ordinary note
export const docExample = 4;
const slashy = /a\/\/b/;
const tpl = `see // inside`;
const tricky = "a \" // b";
const half = 10 / 2;
const jsx = <div>{/* a jsx comment counts */}</div>;
// this one is a real finding
/* prettier-ignore */ // inline directive
const unfinished = "unfinished // count this marker
const multiline = `start
template continuation // count this marker
end`;
const regex = /[// inside regex]/;
export const finding = 4;
