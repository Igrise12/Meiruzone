export const categories = [
  "Recruitment",
  "LinkedIn",
  "Personal",
  "Transaction",
  "Newsletter",
  "Promotion",
  "Spam",
  "Other",
] as const;

export const priorities = ["High", "Medium", "Low"] as const;
export type Category = (typeof categories)[number];
export type Priority = (typeof priorities)[number];
export type CategoryFilter = Category | "Unclassified" | "All";

export type Prediction = {
  category?: Category | null;
  priority?: Priority | null;
  confidence?: number | null;
  reasonCategory?: string | null;
  reasonPriority?: string | null;
  modelVersion?: string | null;
  predictedAt?: string | null;
};

export type HumanLabel = { category: Category | null; priority: Priority | null; confirmedAt: string; source?: "manual" | "correction" };
export type LabelsById = Record<string, HumanLabel>;

export type Email = {
  id: string;
  sender: string;
  address: string;
  subject: string;
  received: string;
  body: string;
  read: boolean;
  hasAttachments: boolean;
  prediction?: Prediction | null;
};

export type CategoryStat = { category: CategoryFilter; count: number; percentage: number };

export const sampleEmails: Email[] = [
  { id: "m01", sender: "Jo Park · Northstar Talent", address: "jo@northstar.example", subject: "Product designer interview — Thursday", received: "9:42 AM", read: false, hasAttachments: false, prediction: { category: "Recruitment", priority: "High", confidence: 61, reasonCategory: "Interview language and a role title match recruitment signals.", reasonPriority: "The message asks for a reply today." }, body: "Hi Rowan,\n\nWe would like to invite you to a first-round interview for the Product Designer role this Thursday at 10:30 AM. Please reply today if that time works.\n\nBest,\nJo" },
  { id: "m02", sender: "TalentWorks", address: "updates@talentworks.example", subject: "Your application has moved to review", received: "10:18 AM", read: true, hasAttachments: false, prediction: { category: "Recruitment", priority: "Medium", confidence: 94 }, body: "Thanks for applying. The hiring team is reviewing your materials and will share an update soon." },
  { id: "m03", sender: "LinkedIn", address: "messages-noreply@linkedin.example", subject: "A new message from Avery Chen", received: "11:06 AM", read: false, hasAttachments: false, prediction: { category: "LinkedIn", priority: "High", confidence: 88 }, body: "Avery Chen sent you a message about the design systems role. Sign in to view the conversation." },
  { id: "m04", sender: "LinkedIn", address: "notifications@linkedin.example", subject: "Three people viewed your profile", received: "Yesterday", read: true, hasAttachments: false, prediction: { category: "LinkedIn", priority: "Low", confidence: 99 }, body: "Your profile appeared in three searches this week. See who's discovering your work." },
  { id: "m05", sender: "Mara Iqbal", address: "mara@postbox.example", subject: "Could you send the draft today?", received: "Yesterday", read: false, hasAttachments: true, prediction: { category: "Personal", priority: "High", confidence: 81, reasonCategory: "A direct request from an individual sender fits personal mail.", reasonPriority: "The sender asks for the draft today." }, body: "Hi Rowan,\n\nCould you send the draft by the end of today? I want to read it before our check-in tomorrow.\n\nThank you,\nMara" },
  { id: "m06", sender: "Sam Rivera", address: "sam@postbox.example", subject: "Saturday lunch?", received: "Mon", read: true, hasAttachments: false, prediction: { category: "Personal", priority: "Low", confidence: 97 }, body: "Want to try the new noodle place this Saturday? No rush—let me know whenever." },
  { id: "m07", sender: "Pine Ledger", address: "billing@pineledger.example", subject: "Invoice PL-2048 is due November 12", received: "Mon", read: false, hasAttachments: true, prediction: { category: "Transaction", priority: "High", confidence: 96 }, body: "Invoice PL-2048 for $84.00 is due November 12. The itemized statement is attached." },
  { id: "m08", sender: "Harbor Rail", address: "trips@harborrail.example", subject: "Your e-ticket for trip HR 531", received: "Sun", read: true, hasAttachments: true, prediction: { category: "Transaction", priority: "Medium", confidence: 92 }, body: "Your e-ticket is ready.\n\nTrip HR 531 departs November 21 at 8:15 AM. Keep this message available for your journey." },
  { id: "m09", sender: "The Small Hours", address: "letters@smallhours.example", subject: "A calmer way to plan your week", received: "Sun", read: true, hasAttachments: false, prediction: { category: "Newsletter", priority: "Low", confidence: 98 }, body: "This week: a five-minute planning ritual, a note on protecting focus, and three reader questions about a steadier routine." },
  { id: "m10", sender: "Garden Table Notes", address: "hello@gardentable.example", subject: "What is in season this month", received: "Sat", read: true, hasAttachments: false, prediction: { category: "Newsletter", priority: "Medium", confidence: 73 }, body: "Late pears, squash, and herbs are in season. We gathered four simple recipes from local growers." },
  { id: "m11", sender: "Coast & Pine", address: "offers@coastpine.example", subject: "A small thank-you: 15% through Friday", received: "Sat", read: false, hasAttachments: false, prediction: { category: "Promotion", priority: "Low", confidence: 89 }, body: "Take 15% off your next order through Friday. Use code THANKS15 at checkout." },
  { id: "m12", sender: "Cedar & Loom", address: "studio@cedarloom.example", subject: "Your saved chair is back in stock", received: "Fri", read: true, hasAttachments: false, prediction: { category: "Promotion", priority: "Medium", confidence: 76 }, body: "The Alder chair you saved is available again in a small batch. No reservation has been made." },
  { id: "m13", sender: "Prize Desk", address: "claim@random-prizes.example", subject: "You have been selected — claim now", received: "Fri", read: false, hasAttachments: false, prediction: { category: "Spam", priority: "Low", confidence: 99 }, body: "Your address was selected for a reward. This is an illustrative sample message, not a real offer." },
  { id: "m14", sender: "Security Notice", address: "alert@sample-service.example", subject: "Unusual sign-in attempt", received: "Thu", read: true, hasAttachments: false, prediction: { category: "Spam", priority: "High", confidence: 58 }, body: "We noticed an unusual sign-in attempt. Review the activity in your account settings." },
  { id: "m15", sender: "Building Desk", address: "notices@riverhouse.example", subject: "Package room access changes next week", received: "Thu", read: false, hasAttachments: false, prediction: { category: "Other", priority: "Medium", confidence: 66 }, body: "The package room will use a new access code beginning next Monday. Residents will receive the code through the building portal." },
  { id: "m16", sender: "Transit Updates", address: "service@cityline.example", subject: "Weekend service advisory", received: "Wed", read: true, hasAttachments: false, prediction: { category: "Other", priority: "Low", confidence: 83 }, body: "Several routes will use alternate stops this weekend. Check the service map before leaving." },
  { id: "m17", sender: "New sender", address: "hello@unknown.example", subject: "A note for Rowan", received: "Tue", read: false, hasAttachments: false, prediction: { category: "Personal", priority: "Medium", confidence: 43, reasonCategory: "The message is too brief for a confident category prediction." }, body: "Hi Rowan,\n\nI have something I think you might find useful. More details soon." },
  { id: "m18", sender: "Local Notes", address: "notes@postbox.example", subject: "A saved note without a prediction", received: "Tue", read: true, hasAttachments: false, body: "This synthetic message has no model prediction or label yet." },
];

// A seeded correction demonstrates that a human label wins over the stored prediction.
export const initialLabels: LabelsById = {
  m16: { category: "Personal", priority: "Low", confirmedAt: "2026-10-01T09:00:00.000Z" },
};
