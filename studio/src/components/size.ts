const UNITS = ["KB", "MB", "GB", "TB"] as const;

/** A byte count for people: "512 B", "2.7 MB", "2.3 GB" (binary units, one decimal). */
export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`;
}
