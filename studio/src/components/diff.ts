export type DiffLine = { op: " " | "-" | "+"; text: string };

// Above this many table cells the changed middle is shown as removed then added (no table of that size)
const MAX_CELLS = 1_000_000;

/** Line diff of two texts (longest common subsequence): kept lines, lines only in ``before`` (-) and only in ``after`` (+). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
  // Lines the texts share at both ends need no table (most edits are local)
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let end = 0;
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
  const kept = (lines: string[]): DiffLine[] => lines.map((text) => ({ op: " ", text }));
  const middleA = a.slice(start, a.length - end);
  const middleB = b.slice(start, b.length - end);
  const middle: DiffLine[] =
    (middleA.length + 1) * (middleB.length + 1) > MAX_CELLS
      ? [...middleA.map((text): DiffLine => ({ op: "-", text })), ...middleB.map((text): DiffLine => ({ op: "+", text }))]
      : tableDiff(middleA, middleB);
  return [...kept(a.slice(0, start)), ...middle, ...kept(a.slice(a.length - end))];
}

function tableDiff(a: string[], b: string[]): DiffLine[] {
  const common: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      common[i][j] = a[i] === b[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      lines.push({ op: " ", text: a[i] });
      i++;
      j++;
    } else if (common[i + 1][j] >= common[i][j + 1]) {
      lines.push({ op: "-", text: a[i++] });
    } else {
      lines.push({ op: "+", text: b[j++] });
    }
  }
  while (i < a.length) lines.push({ op: "-", text: a[i++] });
  while (j < b.length) lines.push({ op: "+", text: b[j++] });
  return lines;
}
