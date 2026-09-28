import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Banner } from './ui';

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * Catches a render error anywhere below it and shows a visible message instead of an unmounted, blank screen -
 * React's default behaviour with no boundary. Key this component by something that changes on navigation (e.g.
 * the route path) so moving to a different page resets it; an error boundary does not reset on its own.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled error while rendering this page:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page-head">
          <Banner kind="error">
            <strong>Something went wrong showing this page.</strong> {this.state.error.message}
          </Banner>
        </div>
      );
    }
    return this.props.children;
  }
}
