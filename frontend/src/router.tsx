import {
  createBrowserRouter,
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigationType,
  useRouteError,
} from 'react-router-dom';
import { useEffect, useState } from 'react';
import { ErrorMessage, FragmentLink } from './ui';

const navigation = [
  ['/', 'Search'],
  ['/books', 'The shelves'],
  ['/intake', 'Book intake'],
  ['/taxonomy', 'Subjects & connections'],
  ['/focus', 'Research focuses'],
  ['/history', 'History'],
  ['/status', 'Library status'],
] as const;

function Appearance() {
  const [choice, setChoice] = useState(() => document.documentElement.dataset.theme ?? 'system');
  useEffect(() => {
    function changed(event: StorageEvent) {
      if (event.key !== null && event.key !== 'reading-room-appearance') return;
      const value =
        event.newValue === 'light' || event.newValue === 'dark' ? event.newValue : 'system';
      setChoice(value);
      if (value === 'system') delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = value;
    }
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);
  return (
    <div className="appearance-control">
      <label htmlFor="appearance">Appearance</label>
      <select
        id="appearance"
        value={choice}
        onChange={(event) => {
          const value = event.target.value;
          setChoice(value);
          if (value === 'system') delete document.documentElement.dataset.theme;
          else document.documentElement.dataset.theme = value;
          try {
            localStorage.setItem('reading-room-appearance', value);
          } catch {
            /* A session-only choice is still useful. */
          }
        }}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </div>
  );
}

function Layout() {
  const location = useLocation();
  const navigationType = useNavigationType();
  useEffect(() => {
    if (navigationType !== 'POP' && !location.hash && !location.state?.readingRoomSearch) {
      document.getElementById('main')?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
  }, [location.key, location.hash, location.state, navigationType]);
  useEffect(() => {
    const key = `reading-room-position:${location.key}`;
    const save = () => {
      try {
        sessionStorage.setItem(
          key,
          JSON.stringify({ y: window.scrollY, focus: document.activeElement?.id ?? '' }),
        );
      } catch {
        /* Navigation remains usable without storage. */
      }
    };
    window.addEventListener('scroll', save, { passive: true });
    window.addEventListener('focusin', save);
    window.addEventListener('pagehide', save);
    return () => {
      window.removeEventListener('scroll', save);
      window.removeEventListener('focusin', save);
      window.removeEventListener('pagehide', save);
    };
  }, [location.key]);
  return (
    <>
      <FragmentLink className="skip-link" href="#main">
        Skip to main content
      </FragmentLink>
      <header className="masthead">
        <div className="masthead-inner">
          <div className="masthead-signature">
            <svg
              className="reading-room-mark"
              viewBox="0 0 48 60"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M3 3h42v54H3z M8 8h32v44H8z M8 30h32 M24 8v12 M24 40v12 M8 20h8 M32 20h8 M8 40h8 M32 40h8" />
              <circle cx="24" cy="30" r="10" />
              <path d="M19 25h10v10H19z" />
            </svg>
            <Link className="wordmark" to="/" aria-label="The Reading Room home">
              <span className="wordmark-small">Your research library</span>
              <span>
                The Reading Room
                <span className="wordmark-dot" aria-hidden="true">
                  .
                </span>
              </span>
            </Link>
          </div>
          <div className="masthead-tools">
            <p className="masthead-note">
              Read closely.
              <br />
              Follow the unexpected.
            </p>
            <Appearance />
          </div>
        </div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navigation.map(([path, label]) => (
            <NavLink key={path} to={path} end={path === '/'}>
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main id="main" tabIndex={-1} className="page-shell min-h-[45vh]">
        <Outlet />
      </main>
      <footer className="site-footer">
        <p>
          A living library, open to new connections.
          <span className="library-dedication">A little of Oxford, wherever you’re reading.</span>
        </p>
        <p>
          Passages are research leads. Read their context and verify exact wording before citing.
        </p>
      </footer>
    </>
  );
}

function RouteError() {
  const error = useRouteError();
  return (
    <main className="page-shell">
      <h1>We couldn’t open that.</h1>
      <ErrorMessage error={error} />
      <p>
        <a href="/">Return to the Reading Room</a>
      </p>
    </main>
  );
}
function NotFound() {
  return (
    <>
      <h1>That page isn’t in the Reading Room.</h1>
      <p>
        <Link to="/">Return to search</Link> or <Link to="/books">browse the shelves</Link>.
      </p>
    </>
  );
}

const reading =
  (
    name:
      | 'BookPage'
      | 'PassagePage'
      | 'UnitPage'
      | 'SelectionPage'
      | 'CitationPage'
      | 'IllustrationPage',
  ) =>
  async () => ({ Component: (await import('./pages/ReadingPages'))[name] });
const admin =
  (
    name:
      | 'TaxonomyPage'
      | 'TaxonomyBooksPage'
      | 'TaxonomyTermPage'
      | 'FocusesPage'
      | 'FocusPage'
      | 'FocusBooksPage'
      | 'HistoryPage'
      | 'StatusPage'
      | 'MetadataPage'
      | 'BibliographyPage',
  ) =>
  async () => ({ Component: (await import('./pages/AdminPages'))[name] });
export const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      {
        path: '/',
        lazy: async () => ({ Component: (await import('./pages/SearchPage')).SearchPage }),
      },
      {
        path: '/search',
        lazy: async () => ({ Component: (await import('./pages/SearchPage')).SearchPage }),
      },
      {
        path: '/books',
        lazy: async () => ({ Component: (await import('./pages/BooksPage')).BooksPage }),
      },
      { path: '/books/:workId', lazy: reading('BookPage') },
      { path: '/read/:passageId', lazy: reading('PassagePage') },
      { path: '/units/:unitId', lazy: reading('UnitPage') },
      { path: '/selections/:selectionId', lazy: reading('SelectionPage') },
      { path: '/cite/unit/:unitId', lazy: reading('CitationPage') },
      { path: '/cite/selection/:selectionId', lazy: reading('CitationPage') },
      { path: '/cite/:passageId', lazy: reading('CitationPage') },
      { path: '/illustration/:fileId', lazy: reading('IllustrationPage') },
      {
        path: '/review/:targetId',
        lazy: async () => ({ Component: (await import('./pages/ReviewPage')).ReviewPage }),
      },
      {
        path: '/review/:targetId/:action',
        lazy: async () => ({ Component: (await import('./pages/ReviewPage')).ReviewPage }),
      },
      {
        path: '/intake',
        lazy: async () => ({ Component: (await import('./pages/IntakePages')).IntakeListPage }),
      },
      {
        path: '/intake/:intakeId',
        lazy: async () => ({ Component: (await import('./pages/IntakePages')).IntakeDetailPage }),
      },
      { path: '/taxonomy', lazy: admin('TaxonomyPage') },
      { path: '/taxonomy/browse', lazy: admin('TaxonomyBooksPage') },
      { path: '/taxonomy/new', lazy: admin('TaxonomyTermPage') },
      { path: '/taxonomy/term/:termId', lazy: admin('TaxonomyTermPage') },
      { path: '/focus', lazy: admin('FocusesPage') },
      { path: '/focus/:focusId', lazy: admin('FocusPage') },
      { path: '/focus/:focusId/books', lazy: admin('FocusBooksPage') },
      { path: '/history', lazy: admin('HistoryPage') },
      { path: '/status', lazy: admin('StatusPage') },
      { path: '/metadata/:targetId', lazy: admin('MetadataPage') },
      { path: '/bibliography/:targetId', lazy: admin('BibliographyPage') },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
