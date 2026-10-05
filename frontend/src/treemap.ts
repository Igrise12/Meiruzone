import { categories, type CategoryFilter, type CategoryStat, type Email, type LabelsById } from "./data";

export const categoryColors: Record<CategoryFilter, string> = {
  Recruitment: "#cfe9f8",
  LinkedIn: "#c8e4f7",
  Personal: "#d8e9dc",
  Transaction: "#f8e6c4",
  Newsletter: "#e6def6",
  Promotion: "#f7dcd4",
  Spam: "#f3d4d7",
  Other: "#dce4eb",
  Unclassified: "#e8edf2",
  All: "#e8edf2",
};

export function categoryStats(emails: Email[], labels: LabelsById): CategoryStat[] {
  const counts = new Map<CategoryFilter, number>([
    ...categories.map((category) => [category, 0] as const),
    ["Unclassified", 0],
  ]);

  for (const email of emails) {
    const category = labels[email.id]?.category ?? email.prediction?.category ?? "Unclassified";
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }

  const total = emails.length;
  return [...counts].map(([category, count]) => ({
    category,
    count,
    percentage: total === 0 ? 0 : Math.round((count / total) * 100),
  }));
}

export type TreemapNode = { stat: CategoryStat } | { left: TreemapNode; right: TreemapNode; leftWeight: number; rightWeight: number };

export function buildTreemap(stats: CategoryStat[]): TreemapNode | null {
  const leaves = stats.filter((stat) => stat.count > 0).sort((a, b) => b.count - a.count);
  if (!leaves.length) return null;
  if (leaves.length === 1) return { stat: leaves[0] };

  const half = leaves.reduce((sum, stat) => sum + stat.count, 0) / 2;
  let running = 0;
  let split = 1;
  let bestDifference = Infinity;
  for (let index = 0; index < leaves.length - 1; index += 1) {
    running += leaves[index].count;
    const difference = Math.abs(half - running);
    if (difference < bestDifference) {
      split = index + 1;
      bestDifference = difference;
    }
  }
  const left = leaves.slice(0, split);
  const right = leaves.slice(split);
  const leftWeight = left.reduce((sum, stat) => sum + stat.count, 0);
  const rightWeight = right.reduce((sum, stat) => sum + stat.count, 0);
  return {
    left: buildTreemap(left)!,
    right: buildTreemap(right)!,
    leftWeight,
    rightWeight,
  };
}
