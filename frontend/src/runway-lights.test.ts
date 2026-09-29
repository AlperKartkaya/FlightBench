import { test } from "node:test";
import assert from "node:assert/strict";
import { isRunwayLightOn } from "./runway-lights.ts";

test("runway light pairs circle through all 20 rows without restarting", () => {
  const litRows = (step: number) => Array.from({ length: 20 }, (_, row) => row)
    .filter((row) => isRunwayLightOn(row, step));
  assert.deepEqual(litRows(0), [0, 4, 8, 12, 16]);
  assert.deepEqual(litRows(1), [1, 5, 9, 13, 17]);
  assert.deepEqual(litRows(19), [3, 7, 11, 15, 19]);
  assert.deepEqual(litRows(20), litRows(0));
});
