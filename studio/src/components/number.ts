/** A decimal as it was set: a value stored as float32 (0.30000001192092896) reads 0.3. Six significant digits are
 * within what a float32 carries, so a value that was set exactly is never rounded away. */
export function decimal(value: number): string {
  return String(Number(value.toPrecision(6)));
}
