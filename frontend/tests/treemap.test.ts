import { describe, expect, it } from "vitest";
import { initialLabels, sampleEmails } from "../src/data";
import { buildTreemap, categoryStats, type TreemapNode } from "../src/treemap";

function leaves(node: TreemapNode | null): number[] {
  if (!node) return [];
  if ("stat" in node) return [node.stat.count];
  return [...leaves(node.left), ...leaves(node.right)];
}

describe("category treemap data", () => {
  it("counts the complete mailbox with human labels ahead of predictions", () => {
    const stats = categoryStats(sampleEmails, initialLabels);
    const counts = Object.fromEntries(stats.map(({ category, count }) => [category, count]));

    expect(Object.values(counts).reduce((sum, count) => sum + count, 0)).toBe(sampleEmails.length);
    expect(counts.Personal).toBe(4);
    expect(counts.Other).toBe(1);
    expect(counts.Unclassified).toBe(1);
    expect(stats.find(({ category }) => category === "Personal")?.percentage).toBe(22);
  });

  it("keeps all categories visible for an empty mailbox and uses zero percentages", () => {
    const stats = categoryStats([], {});
    expect(stats).toHaveLength(9);
    expect(stats.every(({ count, percentage }) => count === 0 && percentage === 0)).toBe(true);
    expect(buildTreemap(stats)).toBeNull();
  });

  it("allocates non-zero tiles only and preserves the full count for skewed data", () => {
    const skewed = Array.from({ length: 20 }, (_, index) => ({
      ...sampleEmails[0],
      id: `skew-${index}`,
      prediction: { category: index === 19 ? "Spam" as const : "Recruitment" as const, priority: "Low" as const, confidence: 90 },
    }));
    const stats = categoryStats(skewed, {});
    expect(leaves(buildTreemap(stats)).sort((a, b) => a - b)).toEqual([1, 19]);
  });
});
