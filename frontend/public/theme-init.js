/* Apply the remembered palette before CSS paints. No source data is executed. */
(() => {
  try {
    const choice = localStorage.getItem('reading-room-appearance');
    if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
  } catch { /* System appearance works when storage is unavailable. */ }
})();
