// Per-user watchlist panel on the markets tab, plus the WATCH button on the
// stock analysis view. Requires account.js (auth state) and index-page.js
// (window.StockScreenAnalyze) — both load before this file.
(function() {
    var body = document.getElementById('watchlistTableBody');
    var addForm = document.getElementById('watchlistAddForm');
    var addInput = document.getElementById('watchlistAddInput');
    var watchBtn = document.getElementById('watchSymbolBtn');
    var utils = window.StockScreenUtils || {};
    var fetchJson = utils.fetchJson;
    var escapeHtml = utils.escapeHtml;
    var sanitizeSymbol = utils.sanitizeSymbol;

    if (!body || !fetchJson) return;

    var symbols = [];
    var authenticated = false;

    function messageRow(html) {
        body.innerHTML = '<tr><td colspan="6" class="text-center py-3 wl-message">' + html + '</td></tr>';
    }

    function renderSignedOut() {
        messageRow('Sign in to build a watchlist that follows you across devices. ' +
            '<button type="button" id="watchlistSignInBtn" class="btn btn-sm btn-outline-secondary ms-2 wl-signin-btn">SIGN IN</button>');
        var btn = document.getElementById('watchlistSignInBtn');
        if (btn) {
            btn.addEventListener('click', function() {
                if (window.StockScreenAuth) window.StockScreenAuth.open();
            });
        }
    }

    function renderEmpty() {
        messageRow('Your watchlist is empty. Add a symbol above, or use WATCH on any stock page.');
    }

    function renderQuotes(quotes) {
        if (!quotes.length) { renderEmpty(); return; }

        body.innerHTML = quotes.map(function(quote) {
            var pct = Number(quote.change_percent || 0);
            var chg = Number(quote.change || 0);
            var dirClass = pct >= 0 ? 'mover-up' : 'mover-down';
            var sign = pct >= 0 ? '+' : '-';
            var cur = escapeHtml(quote.currency || '$');
            var fmt = function(value) {
                return value === null || value === undefined
                    ? '—'
                    : Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
            };
            var safeSymbol = sanitizeSymbol(quote.symbol);
            return '<tr class="mover-row watchlist-row" data-symbol="' + safeSymbol + '">' +
                '<td class="mover-symbol">' + escapeHtml(quote.symbol) + '</td>' +
                '<td class="movers-name">' + escapeHtml(quote.name || '') + '</td>' +
                '<td class="text-end">' + cur + fmt(quote.price) + '</td>' +
                '<td class="text-end ' + dirClass + '">' + sign + cur + fmt(Math.abs(chg)) + '</td>' +
                '<td class="text-end ' + dirClass + '">' + sign + Math.abs(pct).toFixed(2) + '%</td>' +
                '<td class="text-end"><button type="button" class="btn btn-sm btn-outline-secondary watchlist-remove wl-remove-btn" data-symbol="' + safeSymbol + '" title="Remove from watchlist">&times;</button></td>' +
                '</tr>';
        }).join('');

        body.querySelectorAll('.watchlist-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('.watchlist-remove')) return;
                var symbol = this.dataset.symbol;
                if (symbol && typeof window.StockScreenAnalyze === 'function') {
                    window.StockScreenAnalyze(symbol);
                }
            });
        });
        body.querySelectorAll('.watchlist-remove').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                removeSymbol(this.dataset.symbol);
            });
        });
    }

    function refreshPrices() {
        if (!symbols.length) { renderEmpty(); return; }
        fetchJson('/api/quotes?symbols=' + encodeURIComponent(symbols.join(',')))
            .then(function(data) { renderQuotes(data.quotes || []); })
            .catch(function() {
                messageRow('Unable to load watchlist prices right now.');
            });
    }

    function loadWatchlist() {
        messageRow('LOADING WATCHLIST');
        fetchJson('/api/watchlist')
            .then(function(data) {
                symbols = data.symbols || [];
                refreshPrices();
                updateWatchButton();
            })
            .catch(function() {
                messageRow('Unable to load your watchlist right now.');
            });
    }

    function addSymbol(symbol) {
        var clean = sanitizeSymbol(symbol).toUpperCase();
        if (!clean) return;
        fetchJson('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: clean }),
        }).then(function(data) {
            symbols = data.symbols || symbols;
            refreshPrices();
            updateWatchButton();
        }).catch(function(error) {
            messageRow(escapeHtml(error.message || 'Unable to update the watchlist.'));
            window.setTimeout(refreshPrices, 2500);
        });
    }

    function removeSymbol(symbol) {
        var clean = sanitizeSymbol(symbol).toUpperCase();
        if (!clean) return;
        fetchJson('/api/watchlist/' + encodeURIComponent(clean), { method: 'DELETE' })
            .then(function(data) {
                symbols = data.symbols || [];
                refreshPrices();
                updateWatchButton();
            })
            .catch(function(error) {
                messageRow(escapeHtml(error.message || 'Unable to update the watchlist.'));
                window.setTimeout(refreshPrices, 2500);
            });
    }

    function currentAnalysisSymbol() {
        var input = document.getElementById('stockSearch');
        return input ? sanitizeSymbol(input.value).toUpperCase() : '';
    }

    function updateWatchButton() {
        if (!watchBtn) return;
        if (!authenticated) {
            watchBtn.style.display = '';
            watchBtn.textContent = '☆ WATCH';
            watchBtn.title = 'Sign in to add this stock to your watchlist';
            return;
        }
        watchBtn.style.display = '';
        var symbol = currentAnalysisSymbol();
        var watched = symbol && symbols.indexOf(symbol) !== -1;
        watchBtn.textContent = watched ? '★ WATCHING' : '☆ WATCH';
        watchBtn.title = watched ? 'Remove from your watchlist' : 'Add to your watchlist';
    }

    if (watchBtn) {
        watchBtn.addEventListener('click', function() {
            if (!authenticated) {
                if (window.StockScreenAuth) window.StockScreenAuth.open();
                return;
            }
            var symbol = currentAnalysisSymbol();
            if (!symbol) return;
            if (symbols.indexOf(symbol) !== -1) removeSymbol(symbol);
            else addSymbol(symbol);
        });
        // Keep the star in sync as the user analyzes different stocks.
        window.addEventListener('analysis:shown', updateWatchButton);
    }

    if (addForm) {
        addForm.addEventListener('submit', function(e) {
            e.preventDefault();
            addSymbol(addInput.value);
            addInput.value = '';
        });
    }

    window.addEventListener('auth:changed', function(event) {
        authenticated = !!(event.detail && event.detail.authenticated);
        if (addForm) addForm.style.display = authenticated ? 'flex' : 'none';
        if (authenticated) {
            loadWatchlist();
        } else {
            symbols = [];
            renderSignedOut();
            updateWatchButton();
        }
    });

    renderSignedOut();
})();
