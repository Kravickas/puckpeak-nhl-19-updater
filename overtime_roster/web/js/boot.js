// The page's first words and its safety net. A plain script (not a module), so it runs even when a module or a style
// file is missing: before this the window could stay empty with nothing to read.
//   - "Starting..." shows until the page has drawn the app's first data (main.js calls __otOk, Python then knows the
//     window works: Api.page_up).
//   - A file that does not load: the page loads itself again, up to RETRIES times.
//   - Any error of the page, a file that still does not load, or nothing after 25 s: the reason on screen, with
//     "Try again", "Open in my browser" and "Open the start log", and the line goes to logs/start.log (Api.log_js).
(function () {
  var boot = document.getElementById('boot');
  if (!boot) return;
  var done = false, failed = false;
  var waiting = [];               // lines for Python: its calls only exist once the page has loaded
  var RETRIES = 5;
  var LIBRARY_WAIT = 10000;       // ms
  var token = new URLSearchParams(location.search).get('token');

  function api(name, arg) {
    if (token) {                  // browser mode
      return fetch('/api/' + name, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Overtime-Token': token },
        body: JSON.stringify({ args: arg === undefined ? [] : [arg] }),
      }).catch(function () { /* the app is not there */ });
    }
    try {
      var a = window.pywebview && window.pywebview.api;
      if (a && a[name]) return arg === undefined ? a[name]() : a[name](arg);
    } catch (e) { /* the app is not there */ }
  }

  function flush() {
    var there = token || (window.pywebview && window.pywebview.api && window.pywebview.api.log_js);
    while (there && waiting.length) api('log_js', waiting.shift());
  }

  function tell(text) {
    if (waiting.length < 30) waiting.push(String(text).slice(0, 1500));
    flush();
  }
  window.addEventListener('pywebviewready', flush);

  function button(label, click) {
    var b = document.createElement('button');
    b.textContent = label;
    b.style.cssText = 'margin:6px;padding:8px 16px;font:600 14px sans-serif;color:#fff;background:#c2410c;border:1px solid #fb923c;border-radius:4px;cursor:pointer';
    b.onclick = click;
    return b;
  }

  window.__otFail = function (message, fatal, more) {
    tell('FAIL ' + message + (more ? ' ' + more : ''));
    if (failed || (done && !fatal)) return;
    failed = true;
    boot.textContent = '';
    boot.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;z-index:99999;display:flex;flex-direction:column;'
      + 'align-items:center;justify-content:center;text-align:center;padding:24px;background:#14161c;color:#f1f1f1;font:16px sans-serif';
    var title = document.createElement('div');
    title.textContent = 'The window did not start properly';
    title.style.cssText = 'font:700 22px sans-serif;margin-bottom:12px';
    var why = document.createElement('div');
    why.textContent = message;
    why.style.cssText = 'max-width:640px;margin-bottom:8px;color:#a3a3a3';
    var help = document.createElement('div');
    help.textContent = token ? 'Try again. If it keeps happening, send us the start log.'
      : 'Try again. If it keeps happening, open the app in your browser, and send us the start log.';
    help.style.cssText = 'max-width:640px;margin-bottom:16px';
    var row = document.createElement('div');
    row.appendChild(button('Try again', function () { location.reload(); }));
    if (!token) row.appendChild(button('Open in my browser', function () { api('open_in_browser'); }));
    row.appendChild(button('Open the start log', function () { api('open_start_log'); }));
    [title, why, help, row].forEach(function (n) { boot.appendChild(n); });
    if (!boot.parentNode) document.body.appendChild(boot);
  };

  window.__otOk = function () {
    if (done) return;
    done = true;
    failed = false;
    clearTimeout(timer);
    if (boot.parentNode) boot.parentNode.removeChild(boot);
    api('page_up');
  };

  // One file the browser could not get takes the whole page with it (a module's imports fail together). Loading the
  // page again gets it, and the player need not see it.
  var query = new URLSearchParams(location.search);
  var tries = Number(query.get('again') || 0);
  if (tries) tell('loaded again, try ' + tries);

  // Not before the window library has set itself up on this page: it does that once per load, and on the next page it
  // would forget the page's first question, so the page would wait for its data for ever.
  function loadAgain() {
    if (done || tries >= RETRIES) return false;
    function go() {
      query.set('again', tries + 1);
      location.replace(location.pathname + '?' + query.toString());
    }
    var a = window.pywebview && window.pywebview.api;
    if (token || (a && a.ready)) {
      go();
    } else {
      window.addEventListener('pywebviewready', go, { once: true });
      setTimeout(go, LIBRARY_WAIT);
    }
    return true;
  }

  window.addEventListener('error', function (e) {
    if (e.target && e.target !== window && (e.target.src || e.target.href)) {
      if (/^(SCRIPT|LINK)$/.test(e.target.tagName) && loadAgain()) return;
      window.__otFail('A file of the app could not be loaded: ' + (e.target.src || e.target.href));
    } else if (!/ResizeObserver/.test(e.message || '')) {      // the browser's harmless "loop" notice
      window.__otFail('Error in the page: ' + e.message + (e.filename ? ' (' + e.filename + ':' + e.lineno + ')' : ''));
    }
  }, true);
  window.addEventListener('unhandledrejection', function (e) {
    window.__otFail('Error in the page: ' + (e.reason && e.reason.message || e.reason));
  });

  var timer = setTimeout(function () {
    window.__otFail('The app did not send its data in time.');
  }, 25000);
})();
