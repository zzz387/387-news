/* Enhance only missing art. Permanent article HTML and visible text stay intact. */
(() => {
  const front = document.querySelector('.art-front');
  if (!front) return;
  front.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    const tile = img.closest('.art-tile'); img.remove(); tile?.classList.remove('has-art');
  }));
  const tiles = [...front.querySelectorAll('[data-art-key]')].filter(x => !x.querySelector('img'));
  const date = document.querySelector('main[data-issue-date]')?.dataset.issueDate;
  if (!tiles.length || !/^\d{4}-\d{2}-\d{2}$/.test(date || '')) return;
  fetch(`/assets/illustrations/${date}/manifest.json`).then(r => r.ok ? r.json() : null).then(manifest => {
    if (!manifest || manifest.date !== date) return;
    const load = async tile => {
      const art = manifest.images?.[tile.dataset.artKey];
      if (!art || !/^assets\/illustrations\/\d{4}-\d{2}-\d{2}\/[a-f0-9]{64}\.webp$/.test(art.path)) return;
      try {
        const response = await fetch('/' + art.path);
        if (!response.ok) return;
        const data = await response.arrayBuffer();
        const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))].map(x => x.toString(16).padStart(2, '0')).join('');
        if (digest !== art.sha256) return;
        const img = new Image(); img.width = art.width; img.height = art.height;
        img.alt = 'Художественная иллюстрация: ' + tile.querySelector('strong').textContent;
        img.decoding = 'async'; img.src = '/' + art.path;
        await img.decode(); tile.querySelector('.art-media').append(img); tile.classList.add('has-art');
        const label = document.createElement('small'); label.textContent = 'Иллюстрация ИИ · ' + art.genre;
        tile.querySelector('.art-caption').append(label);
      } catch (_) { /* The title remains a complete, keyboard-accessible link. */ }
    };
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(entries => entries.forEach(e => {
        if (e.isIntersecting) { observer.unobserve(e.target); load(e.target); }
      }), {rootMargin: '200px'}); tiles.forEach(tile => observer.observe(tile));
    } else tiles.forEach(load);
  }).catch(() => {});
})();
