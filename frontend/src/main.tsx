import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { fixtureAdapter } from "./api";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App adapter={import.meta.env.VITE_DATA_SOURCE === "fixtures" ? fixtureAdapter : undefined} />
  </React.StrictMode>,
);
