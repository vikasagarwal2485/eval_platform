import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Breadcrumb from './Breadcrumb';

describe('Breadcrumb', () => {
  it('links back to the named list and shows the current record as plain text', () => {
    render(
      <MemoryRouter>
        <Breadcrumb listLabel="Agents" listPath="/agents" current="my-router-agent" />
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', { name: 'Agents' });
    expect(link).toHaveAttribute('href', '/agents');
    expect(screen.getByText('my-router-agent')).toBeInTheDocument();
  });
});
