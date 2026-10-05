import { categories, initialLabels, priorities, sampleEmails, type CategoryStat, type Email, type HumanLabel, type LabelsById, type Priority } from "./data";
import { categoryStats } from "./treemap";

export type SyncResult = { imported: number; completedAt: string };

export type InboxAdapter = {
  getEmails(): Promise<Email[]>;
  getLabels(): Promise<LabelsById>;
  getCategoryStats(): Promise<CategoryStat[]>;
  saveLabel(id: string, label: HumanLabel): Promise<void>;
  sync(): Promise<SyncResult>;
};

const storageKey = "meiruzo-confirmed-labels-v1";

function readLabels(): LabelsById {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey) || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return initialLabels;
    const valid = Object.fromEntries(Object.entries(value).filter((entry): entry is [string, HumanLabel] => {
      const [id, label] = entry;
      return sampleEmails.some((email) => email.id === id) &&
        Boolean(label && categories.includes(label.category) && priorities.includes(label.priority) && typeof label.confirmedAt === "string");
    }));
    return { ...initialLabels, ...valid };
  } catch {
    return initialLabels;
  }
}

export const fixtureAdapter: InboxAdapter = {
  async getEmails() {
    return sampleEmails.map((email) => ({ ...email, prediction: email.prediction ? { ...email.prediction } : undefined }));
  },
  async getLabels() {
    return readLabels();
  },
  async getCategoryStats() {
    return categoryStats(sampleEmails, readLabels());
  },
  async saveLabel(id, label) {
    if (!sampleEmails.some((email) => email.id === id)) throw new Error("Message not found.");
    const labels = readLabels();
    labels[id] = label;
    localStorage.setItem(storageKey, JSON.stringify(labels));
  },
  async sync() {
    return { imported: 0, completedAt: new Date().toISOString() };
  },
};

export function priorityOf(email: Email, labels: LabelsById): Priority | undefined {
  return labels[email.id]?.priority ?? email.prediction?.priority;
}
