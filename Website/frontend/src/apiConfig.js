/**
 * Single source for the API base URL.
 *
 * Five components each hardcoded "http://localhost:8000" and InfoTab used a
 * relative path, so the production bundle called the developer's own machine
 * wherever it was served from, and InfoTab's fetch hit the Vite dev server
 * instead of the API. Set VITE_API_URL at build time to point elsewhere;
 * an empty value means "same origin as this page", which is correct when the
 * backend serves the built bundle itself.
 */
export const BACKEND_URL =
  import.meta.env.VITE_API_URL !== undefined
    ? import.meta.env.VITE_API_URL
    : 'http://localhost:8000';

export default BACKEND_URL;
