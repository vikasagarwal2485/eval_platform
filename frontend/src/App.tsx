import { Link, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import AgentPage from './pages/AgentPage';
import AgentsPage from './pages/AgentsPage';
import ErrorBoundary from './components/ErrorBoundary';
import HistoryPage from './pages/HistoryPage';
import NotFound from './pages/NotFound';
import ProvidersPage from './pages/ProvidersPage';
import ResultsPage from './pages/ResultsPage';
import RunLivePage from './pages/RunLivePage';
import RunSetupPage from './pages/RunSetupPage';
import SuitesPage from './pages/SuitesPage';

const RUN_EVALUATION_PATHS = ['/', '/suites', '/history'];

/** Shared by Run Evaluation setup, Suites and History - they're one section of sub-tabs under the single
 * "Run Evaluation setup" top-level nav item, rather than three separate top-level items. */
function RunEvaluationLayout() {
  return (
    <>
      <nav className="nav" aria-label="Run Evaluation setup sections">
        <NavLink to="/" end>
          Setup
        </NavLink>
        <NavLink to="/suites">Suites</NavLink>
        <NavLink to="/history">History</NavLink>
      </nav>
      <Outlet />
    </>
  );
}

export default function App() {
  const { pathname } = useLocation();
  const runEvaluationActive = RUN_EVALUATION_PATHS.includes(pathname);
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <span className="brand">Model Eval Platform</span>
        <nav className="nav" aria-label="Main">
          <Link to="/" aria-current={runEvaluationActive ? 'page' : undefined}>
            Run Evaluation setup
          </Link>
          <NavLink to="/providers">Models</NavLink>
          <NavLink to="/agents">Agents</NavLink>
        </nav>
        <span className="spacer" />
      </header>
      <main id="main">
        <ErrorBoundary key={pathname}>
          <Routes>
            <Route element={<RunEvaluationLayout />}>
              <Route path="/" element={<RunSetupPage />} />
              <Route path="/suites" element={<SuitesPage />} />
              <Route path="/history" element={<HistoryPage />} />
            </Route>
            <Route path="/runs/:id/live" element={<RunLivePage />} />
            <Route path="/runs/:id" element={<ResultsPage />} />
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/agents/:id" element={<AgentPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </>
  );
}
