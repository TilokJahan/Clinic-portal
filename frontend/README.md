# Frontend

The frontend owner creates the app here (this folder must be empty except for this file):

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm run dev
```

Once `package.json` exists, the CI `frontend` job turns on automatically.
Build against the mock API first, using the contract in `../docs/api.md`.
