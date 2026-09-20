import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { FixtureApi } from "./api/fixture";
import { HttpApi } from "./api/http";
import "./styles.css";

const fixtureMode = import.meta.env.VITE_USE_FIXTURE === "true";
const api = fixtureMode
  ? new FixtureApi()
  : new HttpApi(import.meta.env.VITE_API_BASE_URL ?? "/api/v1");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={api} fixtureMode={fixtureMode} />
  </StrictMode>,
);
