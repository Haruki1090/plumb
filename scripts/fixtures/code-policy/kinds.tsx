// a license header comment at the top of a new file
// it spans two lines
export const allowedHeader = 1;
/**
 * A doc comment directly above an export.
 */
export function docExport(): number {
  // prettier-ignore
  return 2;
}
/* prettier-ignore */
export const ignored = 3;
const slashy = /a\/\/b/;
const tpl = `see // inside`;
const tricky = "a \" // b";
const half = 10 / 2;
const jsx = <div>{/* a jsx comment counts */}</div>;
// this one is a real finding
export const finding = 4;
