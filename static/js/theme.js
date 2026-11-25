/* Runs in <head> before first paint so the saved theme never flashes. Defaults to dark. */
(function () {
  var theme = 'dark';
  try {
    var saved = localStorage.getItem('rupee-ledger-theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
  } catch (e) { /* storage blocked: keep the default */ }
  document.documentElement.setAttribute('data-theme', theme);
})();
