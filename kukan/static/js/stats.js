// Fills in the S and T timings on a list page's stats line.
//
// The Buefy table measured these itself around its axios call: S when the
// response arrived, T once the new rows were on screen. htmx fires equivalent
// events, so the numbers mean the same thing they did before.
//
// Delegated from document, because #results is replaced on every swap -- a
// listener bound to the element itself would go with it.
(function () {
    let started = null;
    let serverMs = null;

    document.addEventListener('htmx:beforeRequest', function (event) {
        if (event.detail.target && event.detail.target.id === 'results') {
            started = performance.now();
            serverMs = null;
        }
    });

    document.addEventListener('htmx:afterOnLoad', function () {
        if (started !== null) {
            serverMs = Math.round(performance.now() - started);
        }
    });

    // afterSwap, not afterSettle: settle waits out htmx's transition delay,
    // which would make T look like the server was slow.
    document.addEventListener('htmx:afterSwap', function (event) {
        if (started === null || !event.target.querySelector) {
            return;
        }
        const stats = document.getElementById('results-stats');
        if (!stats) {
            return;
        }
        const totalMs = Math.round(performance.now() - started);
        const server = stats.querySelector('[data-stat="server"]');
        const total = stats.querySelector('[data-stat="total"]');
        if (server) {
            server.textContent = 'S:' + (serverMs === null ? '-' : serverMs);
        }
        if (total) {
            total.textContent = 'T:' + totalMs;
        }
        started = null;
    });
})();
