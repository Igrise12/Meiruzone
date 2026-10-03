# Client Brief: Local-First Smart Email Classification

## Project summary

Build a lightweight application that helps a person make sense of an existing email inbox. It connects to an email account through IMAP, keeps the working data and machine-learning workflow on the user's computer, and organizes messages into useful categories with a separate priority level.

The product is a **Smart Inbox companion**, not a replacement email client. Its first release focuses on classification, review, and learning from user corrections. It will not send email or make changes to the user's mailbox.

## The problem

Important messages compete for attention with newsletters, promotions, automated notifications, and other low-priority mail. Generic inbox rules can be rigid, while cloud AI tools may require sending private email content to an outside service.

This project aims to provide practical organization and a personal classification model while keeping processing local by default.

## Goals for the MVP

The user should be able to:

1. Connect an account using IMAP and retrieve recent or unread messages.
2. Review parsed messages stored on their own machine.
3. Label messages by category and priority.
4. Train a baseline classifier from those labels.
5. See automatic predictions, confidence, and items that need review.
6. Correct mistakes and retain those corrections as future training examples.
7. Use the complete workflow locally, without a cloud service.

## Intended users

The first user is an individual who wants a personal inbox organization tool and is willing to label some messages to improve their own classifier. The initial experience should favor clarity, reversibility, and understandable predictions over automation that changes mailbox state.

## Product experience

The Smart Inbox presents a searchable or filterable list of locally synced messages with category, priority, and confidence indicators. Users can open a message, inspect its relevant content, and accept or correct its prediction. Low-confidence messages appear in a “Needs Review” state. Basic statistics can show how messages are distributed across categories.

The first category set is:

- Recruitment
- LinkedIn
- Personal
- Transaction
- Newsletter
- Promotion
- Spam
- Other

Priority is a separate three-level assessment: High, Medium, or Low. For example, a Recruitment message may be High priority, while a LinkedIn notification may be Low priority.

## How it works

The application retrieves email through IMAP, extracts sender, subject, clean text, received date, read/unread status, and whether attachments are present, then saves the required data in a local SQLite database. A traditional machine-learning model uses sender, subject, and body text to estimate a category and confidence. Simple rules or a separate baseline model assign priority.

The first classifier is TF-IDF with Logistic Regression. The user can correct its output; those labels are available for a later, deliberate model training run. The product reports useful evaluation measures such as per-category precision, recall, F1, macro F1, and a confusion matrix, since category counts may be uneven.

## Privacy and trust

- Email content, database records, inference, and model files stay local by default.
- Email passwords and tokens are not stored in source code or committed to Git.
- Logs avoid full email bodies and secrets.
- Private messages, training data, local database files, and personal model artifacts are excluded from the repository.
- The application does not automatically send email content to an LLM or other external AI service.
- The application does not automatically send, reply to, delete, or move messages.

## Proposed technology

- **Frontend:** React for the Smart Inbox, filters, review, correction, and basic statistics.
- **Backend:** Python and FastAPI for the local API, sync coordination, persistence, and inference.
- **Email access:** IMAP for retrieving messages; SMTP is out of scope.
- **Storage:** SQLite initially, with an option to consider PostgreSQL only if future needs warrant it.
- **Machine learning:** scikit-learn, TF-IDF, Logistic Regression, and locally stored Joblib artifacts.
- **Development and delivery:** Docker/Compose as a packaging option and GitHub Actions for continuous integration.

## Scope boundaries

### Included

- IMAP connection and retrieval of recent or unread messages.
- Parsing and local storage of the fields needed by the application.
- Manual category and priority labeling.
- Baseline category training, evaluation, and local inference.
- Basic priority assignment.
- Confidence display, “Needs Review,” and prediction correction.
- Smart Inbox views and basic category statistics.
- Local setup documentation and CI checks.

### Not included in the first release

- Sending or replying to email.
- Automatically deleting, moving, or otherwise modifying mailbox messages.
- Replacing a full email client.
- Required cloud hosting or external AI services.
- LLM-based summaries, reply suggestions, or low-confidence fallback.
- Large Transformer models, automatic continuous retraining, or a full agent system.
- Kubernetes or distributed processing infrastructure.
- Automatic production deployment.

## Delivery approach

1. **Connect and retrieve:** prove IMAP connectivity and parse messages.
2. **Store locally:** persist messages in SQLite and make sync repeatable.
3. **Build labeled data:** allow manual category and priority labels.
4. **Train a baseline:** fit and evaluate TF-IDF plus Logistic Regression.
5. **Serve predictions:** connect inference and feedback to FastAPI.
6. **Build the Smart Inbox:** display and filter messages, expose review and correction.
7. **Make it reproducible:** document local setup and add CI for lint, tests, and builds.

## Definition of success

The MVP succeeds when a user can retrieve real messages over IMAP, store and classify them locally, label examples, train and evaluate a model, see category/confidence and priority predictions in the Smart Inbox, correct those predictions, and repeat the setup from documented instructions. Automated CI checks should validate changes before they are merged.

## Later opportunities

Once the core workflow is dependable, the product could explore local LLM support for summaries, action items, deadlines, explanations, search, or low-confidence classification. These are future options and should preserve the local-first privacy expectation.
