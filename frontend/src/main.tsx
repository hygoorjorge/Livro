import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes, NavLink, Navigate } from "react-router-dom";
import { LawsLibrary } from "./pages/LawsLibrary";
import { Upload } from "./pages/Upload";
import { Review } from "./pages/Review";
import { FigureReview } from "./pages/FigureReview";
import { Verify } from "./pages/Verify";
import "./styles.css";

function Shell() {
  return (
    <div className="shell">
      <nav className="nav">
        <h1>Atualizador do Livro</h1>
        <NavLink to="/laws">Leis & Mappings</NavLink>
        <NavLink to="/upload">Upload do Livro</NavLink>
        <NavLink to="/review">Revisão</NavLink>
        <NavLink to="/figures">Figuras</NavLink>
        <NavLink to="/verify">Verificar & Exportar</NavLink>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/laws" />} />
          <Route path="/laws" element={<LawsLibrary />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/review" element={<Review />} />
          <Route path="/figures" element={<FigureReview />} />
          <Route path="/verify" element={<Verify />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </React.StrictMode>
);
