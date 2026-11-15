# Frontend development

The browser UI is a React application. Install the frontend packages once, build the static bundle, then run the Python service from the repository root.

```powershell
cd stitch_aesthetic_markdown_reader
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m fods.cli serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. The build writes to `src/fods/web/dist`, which the Python service serves from the same origin as its API and event stream. Rebuild after changing the React frontend.

For frontend-only iteration, run `npm run dev` from `stitch_aesthetic_markdown_reader`; Vite proxies `/api` to the Python service on port 8765.
