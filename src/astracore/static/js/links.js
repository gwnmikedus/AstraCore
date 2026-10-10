// Browser-rendered counterpart of templates/_links.html.
(function () {
  'use strict';
  AC.externalLink = function (href, label, {cls = '', symbol = '', newTab = true} = {}) {
    let url;
    try { url = new URL(href); } catch (error) { return AC.esc(label); }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return AC.esc(label);
    symbol = symbol || (url.hostname === 'github.com' ? 'github' : '');
    const leading = symbol ? AC.icon(symbol, `link-symbol icon-${symbol}`) + ' ' : '';
    const target = newTab ? ' target="_blank" rel="noopener noreferrer"' : '';
    const description = newTab ? 'external site, opens in a new tab' : 'external site';
    return `<a href="${AC.esc(url.href)}" class="external-link ${AC.esc(cls)}"${target}>${leading}${AC.esc(label)} ${AC.icon('external-link', 'external-indicator')}<span class="sr-only"> (${description})</span></a>`;
  };
})();
