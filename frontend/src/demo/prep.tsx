// Entry of prep mode (prep.html, admin only). Served by the demo dev server (vite.demo.config.ts); it is not part
// of the presentation build.
import React from "react";
import ReactDOM from "react-dom/client";
import "../index.css";
import "./demo.css";
import PrepMode from "./PrepMode";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PrepMode />
  </React.StrictMode>
);
