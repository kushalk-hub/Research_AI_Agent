import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./app/App.jsx";
import { StoreProvider } from "./store/store.jsx";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/app.css";

const container = document.getElementById("root");
if (!container) throw new Error("Missing #root element");

createRoot(container).render(
  <StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </StrictMode>,
);
