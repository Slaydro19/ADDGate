import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

const DEV = import.meta.env.DEV;
if (DEV) document.title = "[DEV] ADDGate";

createRoot(document.getElementById("root")).render(
  <>
    <App />
    {DEV && (
      <div className="dev-badge" role="status" aria-label={`Development build, branch ${__GIT_BRANCH__}`}>
        <span className="dev-dot" aria-hidden="true" />
        DEV{__GIT_BRANCH__ && ` · ${__GIT_BRANCH__}`}
      </div>
    )}
  </>
);
