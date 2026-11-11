import { createRoot } from "react-dom/client";
import App from "./App";
import { login } from "./api";
import "./style.css";

login().then(() => createRoot(document.getElementById("root")!).render(<App />));
