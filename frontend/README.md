# Meiruzo frontend

The React preview uses synthetic messages only. Confirmed labels are stored in this browser's local storage; mailbox setup and sync are demos and do not connect to a server.

## Requirements

- Node.js 20.19+ or 22.12+
- npm 10+

## Commands

From this directory:

```bash
npm install
npm run dev
```

Vite prints the local preview URL, normally `http://localhost:5173`.

```bash
npm test
npm run lint
npm run typecheck
npm run build
npm run preview
```

`npm run build` checks TypeScript and creates the production bundle in `dist/`. `npm run preview` serves that built bundle locally.
