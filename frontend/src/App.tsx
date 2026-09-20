import { NavLink, Route, Routes } from 'react-router-dom';
import HistoryPage from './pages/HistoryPage';
import NotFound from './pages/NotFound';
import ResultsPage from './pages/ResultsPage';
import RunLivePage from './pages/RunLivePage';
import RunSetupPage from './pages/RunSetupPage';
import SuitesPage from './pages/SuitesPage';

export default function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <span className="brand">LLM Eval Platform</span>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            Run setup
          </NavLink>
          <NavLink to="/suites">Suites</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
        <span className="spacer" />
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<RunSetupPage />} />
          <Route path="/runs/:id/live" element={<RunLivePage />} />
          <Route path="/runs/:id" element={<ResultsPage />} />
          <Route path="/suites" element={<SuitesPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}
