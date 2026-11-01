import { screen } from '@testing-library/react';
import { renderApp } from '../test/utils';
import NotFound from './NotFound';

test('renders with the shared empty-state vocabulary, not bare text', () => {
  const { container } = renderApp(<NotFound />);
  const empty = container.querySelector('.empty');
  expect(empty).toBeTruthy();
  expect(empty?.querySelector('h1')).toHaveTextContent('Page not found');
  expect(screen.getByRole('link', { name: 'Go to run setup' })).toHaveAttribute('href', '/');
});
