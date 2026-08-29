import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary, RootErrorFallback } from "./components/ErrorBoundary";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary label="App" fallback={<RootErrorFallback />}>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
