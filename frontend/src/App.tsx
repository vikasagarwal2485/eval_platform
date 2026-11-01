import { Link, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import AgentPage from './pages/AgentPage';
import AgentsPage from './pages/AgentsPage';
import { ConfirmProvider } from './components/ConfirmDialog';
import ErrorBoundary from './components/ErrorBoundary';
import ThemeToggle from './components/ThemeToggle';
import { ToastProvider } from './components/Toast';
import HistoryPage from './pages/HistoryPage';
import NotFound from './pages/NotFound';
import ProvidersPage from './pages/ProvidersPage';
import ResultsPage from './pages/ResultsPage';
import RunLivePage from './pages/RunLivePage';
import RunSetupPage from './pages/RunSetupPage';
import SkillsPage from './pages/SkillsPage';
import SuitesPage from './pages/SuitesPage';

const RUN_EVALUATION_PATHS = ['/', '/suites', '/history'];

/** Small abstract mark - three ascending bars - standing in for a real logo until one exists. */
function BrandMark() {
  return (
    <svg
      className="brand-mark"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <rect x="1" y="9" width="3.2" height="6" rx="0.8" fill="currentColor" />
      <rect x="6.4" y="5" width="3.2" height="10" rx="0.8" fill="currentColor" />
      <rect x="11.8" y="1" width="3.2" height="14" rx="0.8" fill="currentColor" />
    </svg>
  );
}

/** Shared by Run Evaluation setup, Suites and History - they're one section of sub-tabs under the
 * single "Run Evaluation setup" top-level nav item, rather than separate top-level items. Skills
 * (add-run-skills) is its own top-level item instead, next to Models and Agents
 * (add-agent-playground) - it's no longer scoped to benchmark runs alone, a registered skill is
 * now equally attachable to a live agent's Playground spawn, so it doesn't belong nested under
 * "Run Evaluation setup" specifically. */
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
    <ToastProvider>
      <ConfirmProvider>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="app-header">
          <span className="brand">
            <BrandMark />
            Model Eval Platform
          </span>
          <nav className="nav" aria-label="Main">
            <Link to="/" aria-current={runEvaluationActive ? 'page' : undefined}>
              Run Evaluation setup
            </Link>
            <NavLink to="/providers">Models</NavLink>
            <NavLink to="/skills">Skills</NavLink>
            <NavLink to="/agents">Agents</NavLink>
          </nav>
          <span className="spacer" />
          <ThemeToggle />
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
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/agents/:id" element={<AgentPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </ConfirmProvider>
    </ToastProvider>
  );
}
