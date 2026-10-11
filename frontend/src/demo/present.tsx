// Entry of the audience presentation (demo.html). Reads only /demo_cache: it imports nothing from api.ts.
import ReactDOM from "react-dom/client";
import "../index.css";
import "./demo.css";
import Presentation from "./Presentation";

ReactDOM.createRoot(document.getElementById("root")!).render(<Presentation />);
