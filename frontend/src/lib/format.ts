/**
 * Dates as DBIM asks (Annex A.5.6 viii): day before month, dd/mm/yyyy, with a
 * 24-hour time. One formatter so every page shows dates the same way.
 */
const DATE_TIME = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
});
const DATE = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });

export function formatDateTime(iso: string | number | Date): string {
  return DATE_TIME.format(new Date(iso));
}

export function formatDate(iso: string | number | Date): string {
  return DATE.format(new Date(iso));
}
