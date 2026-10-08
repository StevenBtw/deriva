export type DiffLine = { op: " " | "-" | "+"; text: string };

/** Line diff of two texts (longest common subsequence): kept lines, lines only in ``before`` (-) and only in ``after`` (+). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
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
