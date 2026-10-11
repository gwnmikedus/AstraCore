// Read-only browser audit: evaluate on each page, theme and viewport under review.
(() => {
  const failures = [];
  const headers = [];
  const selectors = 'h1, h2, h3, p, a, button, label, .eyebrow, .ctx';
  for (const header of document.querySelectorAll('.context-header, .command-header, .community-header')) {
    const image = header.querySelector('.context-art, .community-header-art');
    const art = image?.getBoundingClientRect();
    const visibleArt = art && art.width > 0 && art.height > 0;
    const title = header.querySelector('h1, h2')?.textContent.trim() || 'Context header';
    let checked = 0;
    for (const element of header.querySelectorAll(selectors)) {
      const bounds = element.getBoundingClientRect();
      if (!bounds.width || !bounds.height) continue;
      checked++;
      if (visibleArt && bounds.left < art.right && bounds.right > art.left
          && bounds.top < art.bottom && bounds.bottom > art.top) {
        failures.push({header: title, element: element.tagName, issue: 'Content overlaps artwork'});
      }
      if (bounds.left < -1 || bounds.right > window.innerWidth + 1) {
        failures.push({header: title, element: element.tagName, issue: 'Content exceeds viewport'});
      }
    }
    headers.push({title, checked, artworkVisible: Boolean(visibleArt)});
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) {
    failures.push({issue: 'Page has horizontal overflow'});
  }
  const toggle = document.querySelector('.menu-toggle')?.getBoundingClientRect();
  const mark = document.querySelector('.menu-mark')?.getBoundingClientRect();
  const content = document.querySelector('main.container')?.getBoundingClientRect();
  if (toggle && (toggle.width !== 48 || toggle.height !== 48)) {
    failures.push({issue: 'Menu button geometry changed'});
  }
  if (mark && (mark.width !== 28 || mark.height !== 28)) {
    failures.push({issue: 'Menu icon geometry changed'});
  }
  if (window.innerWidth >= 1080 && toggle && content && toggle.right > content.left) {
    failures.push({issue: 'Desktop menu overlaps content pane'});
  }
  return {viewport: [window.innerWidth, window.innerHeight],
    theme: document.documentElement.dataset.theme || 'dark', headers, failures};
})();
