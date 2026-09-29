export function isRunwayLightOn(row: number, step: number): boolean {
  return (row - step) % 4 === 0;
}
