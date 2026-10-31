import { describe, expect, it } from 'vitest';
import { COMMUNITY_RATING_THRESHOLD, bayesianScore } from './RatingSummary';

/** The API computes the score; this local formula is only a fallback. These are the values the backend
 *  tests assert for the same inputs (`test_rating_exclusion.py`, Review.md 6.1), so the two cannot drift. */
const fromTotals = (sum: number, count: number) => bayesianScore({ average: sum / count, count, category_averages: [] });

describe('bayesianScore (fallback for the server score)', () => {
  it('matches the server formula (sum + 5 * 3.5) / (count + 5)', () => {
    expect(fromTotals(25, 5)).toBeCloseTo(4.25, 10); // five perfect reviews do not give 5
    expect(fromTotals(10, 5)).toBeCloseTo(2.75, 10);
    expect(fromTotals(15, 5)).toBeCloseTo(3.25, 10);
    expect(fromTotals(500, 100)).toBeCloseTo(517.5 / 105, 10);
  });

  it('has no score without reviews and uses the threshold of five', () => {
    expect(bayesianScore({ average: null, count: 0, category_averages: [] })).toBeNull();
    expect(COMMUNITY_RATING_THRESHOLD).toBe(5);
  });

  it('stays between 1 and 5 and rises with the average', () => {
    const low = fromTotals(5, 5) as number;
    const high = fromTotals(25, 5) as number;
    expect(low).toBeGreaterThan(1);
    expect(high).toBeLessThan(5);
    expect(high).toBeGreaterThan(low);
  });
});
