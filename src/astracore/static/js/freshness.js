// Refresh on visit (#75): Home and Operate render at once from stored data; when it's stale the
// freshness line carries data-auto-refresh, and this asks the server to read the stale characters
// from ESI, then reloads the page to show the new data. Needs astracore.js (AC.post).
(function () {
  async function autoRefresh(el, {post = window.AC.post, reload = () => window.location.reload(), wait = ms => new Promise(r => setTimeout(r, ms))} = {}) {
    const url = el && el.dataset && el.dataset.autoRefresh;
    if (!url) return 'skipped';
    const busy = el.querySelector('.freshness-busy');
    const say = text => { if (busy) busy.textContent = text; };
    const r = await post(url, {});
    if (r && r.refreshed) {
      const problems = Object.entries(r.problems || {});
      if (problems.length) {
        const [name, why] = problems[0];
        say(problems.length === 1 ? `updated, except ${name} (${why})`
          : `${problems.length} characters couldn’t be read (${why})`);
        await wait(4000);   // long enough to read before the page reloads
      } else {
        say('updated, reloading…');
      }
      reload();
      return 'reloaded';
    }
    if (el.classList) el.classList.add('is-stale');
    say(r && r.error ? 'couldn’t refresh, try Refresh now on your profile' : 'refreshed recently, try again in a few minutes');
    return 'kept';
  }

  window.AC = Object.assign(window.AC || {}, {autoRefresh});
  if (typeof document !== 'undefined' && document.querySelector) {
    const start = () => { const el = document.querySelector('[data-auto-refresh]'); if (el) autoRefresh(el); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  }
})();
