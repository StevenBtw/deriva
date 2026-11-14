/** A decimal as it was set: a value stored as float32 (0.30000001192092896) reads 0.3. Seven significant digits are
 * about what a float32 carries: a value set with seven digits keeps them, and one set with fewer reads as it was set. */
export function decimal(value: number): string {
  return String(Number(value.toPrecision(7)));
}
