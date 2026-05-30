# Secure AI Agent Architecture (Local-First)
This scaffold implements a secure local backend for AI agents (OpenCode/OpenWebUI) to access Notion and local tools without exposing secrets to the model.
## Security model
- Agent can only call `/tools/execute` with an allowlisted tool name.
- Gateway validates input, blocks destructive intent, and enforces filesystem boundaries.
- Backend executes tool logic only after gateway approval.
- Secrets are loaded from environment variables at runtime, never hardcoded.
## Architecture
1. Agent (OpenCode / OpenWebUI cloud model) sends tool calls.
2. Gateway (`gateway/`) validates payload + permissions.
3. Tools (`tools/`) run local actions (Notion, filesystem).
4. Responses are sanitized before returning to agent.
## Folder structure
```text
secure-ai-agent-architecture/
├─ server.js
├─ gateway/
│  ├─ constants.js
│  ├─ index.js
│  ├─ schemas.js
│  └─ validators.js
├─ tools/
│  ├─ notionRead.js
│  ├─ notionWrite.js
│  └─ filesystem.js
├─ routes/
│  └─ tools.js
├─ middleware/
│  ├─ errorHandler.js
│  └─ requestLogger.js
├─ .env.example
├─ .gitignore
├─ opencode.example.json
└─ package.json
```
Runtime safe directory (configurable with `SAFE_WORKSPACE_ROOT`, default `/safe_workspace/`).
## Environment setup
1. Copy `.env.example` to `.env`.
2. Fill placeholders locally:
   - `NOTION_TOKEN=YOUR_NOTION_TOKEN_HERE`
   - `NOTION_DATABASE_ID=YOUR_DATABASE_ID_HERE`
   - `SAFE_WORKSPACE_ROOT=./safe_workspace` (recommended on macOS local setup)
   - `PORT=3001` (3000 is commonly occupied by other local apps)
3. Install dependencies and run:
   - `npm install`
   - `npm start`
## Tool policy
### Allowed
- `notion.readPages`
- `notion.createNote`
- `notion.updateLimitedContent`
- `fs.readFile`
- `fs.writeFile`
### Forbidden by design
- Any delete operation
- Any arbitrary shell command execution
- Access outside configured `SAFE_WORKSPACE_ROOT`
- Access to `.env`, `/tmp`, system directories
## Example request from agent
`POST /tools/execute`
```json
{
  "tool": "fs.writeFile",
  "args": {
    "path": "notes/today.txt",
    "content": "safe content"
  }
}
```
The gateway resolves this path inside `SAFE_WORKSPACE_ROOT` and blocks traversal attempts.
## Integration note for `opencode.json`
Use `opencode.example.json` as a base and point the tool endpoint to:
- `http://127.0.0.1:3001/tools/execute` (or the same port configured in `.env`)
Ensure your orchestrator sends only `{ tool, args }` payloads and never raw credentials.
