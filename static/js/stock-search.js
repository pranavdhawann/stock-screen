// "Track a Stock" search widget (Track page).
//
// The full analysis view — charts, insights, sentiment news — lives on the
// Markets page, driven by index-page.js and reachable from the movers table
// too. This widget owns only symbol *selection*: pick a stock here and the
// browser is sent to /?symbol=SYM, which index-page.js picks up on load and
// analyses. That keeps one implementation of the analysis flow rather than
// shipping index-page.js (and Chart.js) to this page as well.
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('stockSearch');
    const sentimentForm = document.getElementById('sentimentForm');
    const sampleStocksDropdown = document.getElementById('sampleStocksDropdown');
    const autocompleteDropdown = document.getElementById('autocompleteDropdown');
    if (!searchInput || !sentimentForm) return;

    const marketSelect = document.getElementById('marketSelect');

    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeSymbol = utils.sanitizeSymbol || (value => String(value ?? '').replace(/[^A-Za-z0-9.^-]/g, ''));
    const fetchJson = utils.fetchJson || ((url, options) => fetch(url, options).then(r => r.json()));
    const trackEvent = utils.trackEvent || (() => {});

    const AUTOCOMPLETE_DEBOUNCE_MS = 150;
    let searchTimeout;
    let autocompleteController = null;
    let currentAutocompleteIndex = -1;

    function currentMarket() {
        return marketSelect && marketSelect.value === 'IN' ? 'IN' : 'US';
    }

    // ── Hand-off ──────────────────────────────────────────────────────────
    function analyze(symbol) {
        const clean = sanitizeSymbol(symbol).toUpperCase();
        if (!clean) return;
        trackEvent('analyze-stock', { symbol: clean, market: currentMarket(), from: 'track' });
        window.location.href = `/?symbol=${encodeURIComponent(clean)}#news`;
    }

    // ── Floating dropdowns ────────────────────────────────────────────────
    // Both dropdowns are positioned as fixed overlays anchored to the input so
    // they escape the card's stacking/overflow context.
    function positionFloatingDropdown(dropdown) {
        if (!dropdown) return;
        const rect = searchInput.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.left = `${rect.left}px`;
        dropdown.style.top = `${rect.bottom + 2}px`;
        dropdown.style.width = `${rect.width}px`;
        dropdown.style.maxWidth = `${rect.width}px`;
        dropdown.style.zIndex = '5000';
        dropdown.style.transform = 'none';
        dropdown.style.inset = 'auto';
    }

    function showSampleStocksDropdown() {
        if (!sampleStocksDropdown) return;
        positionFloatingDropdown(sampleStocksDropdown);
        sampleStocksDropdown.style.display = 'block';
        sampleStocksDropdown.classList.add('show');
    }

    function hideSampleStocksDropdown() {
        if (!sampleStocksDropdown) return;
        sampleStocksDropdown.classList.remove('show');
        sampleStocksDropdown.style.display = 'none';
    }

    function dismissAutocomplete() {
        if (autocompleteDropdown) autocompleteDropdown.style.display = 'none';
        currentAutocompleteIndex = -1;
    }

    function repositionOpenDropdowns() {
        if (sampleStocksDropdown && sampleStocksDropdown.style.display === 'block') {
            positionFloatingDropdown(sampleStocksDropdown);
        }
        if (autocompleteDropdown && autocompleteDropdown.style.display === 'block') {
            positionFloatingDropdown(autocompleteDropdown);
        }
    }
    window.addEventListener('resize', repositionOpenDropdowns);
    window.addEventListener('scroll', repositionOpenDropdowns, true);

    // ── Sample-stock list (populated from /api/stock_list) ─────────────────
    function toggleStockSections(market) {
        const usSection = document.getElementById('usStocksSection');
        const inSection = document.getElementById('indianStocksSection');
        if (usSection) usSection.style.display = market === 'IN' ? 'none' : 'block';
        if (inSection) inSection.style.display = market === 'IN' ? 'block' : 'none';
    }

    function loadStockDropdown() {
        fetchJson('/api/stock_list')
            .then(data => {
                const usSection = document.getElementById('usStocksSection');
                const inSection = document.getElementById('indianStocksSection');
                if (usSection && data.US) {
                    usSection.innerHTML = data.US.map(s =>
                        `<a class="dropdown-item" href="#" data-symbol="${sanitizeSymbol(s.symbol)}">${escapeHtml(s.name)} (${escapeHtml(s.symbol)})</a>`
                    ).join('');
                }
                if (inSection && data.IN) {
                    inSection.innerHTML = data.IN.map(s =>
                        `<a class="dropdown-item" href="#" data-symbol="${sanitizeSymbol(s.symbol)}">${escapeHtml(s.name)} (${escapeHtml(s.symbol)})</a>`
                    ).join('');
                }
            })
            .catch(error => console.error('Error loading stock list:', error));
    }

    toggleStockSections(currentMarket());
    loadStockDropdown();

    if (marketSelect) {
        marketSelect.addEventListener('change', function() {
            toggleStockSections(currentMarket());
            // Stale US/IN autocomplete results shouldn't linger across a
            // market switch.
            if (autocompleteController) {
                autocompleteController.abort();
                autocompleteController = null;
            }
            dismissAutocomplete();
        });
    }

    if (sampleStocksDropdown) {
        sampleStocksDropdown.addEventListener('click', function(e) {
            e.preventDefault();
            if (e.target.classList.contains('dropdown-item')) {
                hideSampleStocksDropdown();
                analyze(e.target.dataset.symbol);
            }
        });
    }

    // ── Autocomplete ──────────────────────────────────────────────────────
    function displayAutocomplete(results) {
        if (!autocompleteDropdown || !Array.isArray(results) || results.length === 0) {
            dismissAutocomplete();
            return;
        }

        autocompleteDropdown.innerHTML = results.map(stock => `
            <div class="autocomplete-item" data-symbol="${sanitizeSymbol(stock.symbol)}">
                <strong>${escapeHtml(stock.symbol)}</strong> - ${escapeHtml(stock.name)}
            </div>
        `).join('');

        positionFloatingDropdown(autocompleteDropdown);
        autocompleteDropdown.style.display = 'block';
        currentAutocompleteIndex = -1;

        autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', function() {
                dismissAutocomplete();
                analyze(this.dataset.symbol);
            });
        });
    }

    searchInput.addEventListener('focus', function() {
        if (this.value.trim() === '') showSampleStocksDropdown();
    });

    searchInput.addEventListener('click', function() {
        if (this.value.trim() !== '') {
            this.value = '';
            showSampleStocksDropdown();
        }
    });

    searchInput.addEventListener('input', function() {
        const query = this.value.trim();
        clearTimeout(searchTimeout);
        hideSampleStocksDropdown();

        if (query.length < 1) {
            dismissAutocomplete();
            return;
        }

        searchTimeout = setTimeout(() => {
            if (autocompleteController) autocompleteController.abort();
            autocompleteController = new AbortController();
            fetchJson(
                `/api/search_stocks?q=${encodeURIComponent(query)}&market=${currentMarket()}`,
                { signal: autocompleteController.signal },
            )
                .then(displayAutocomplete)
                .catch(error => {
                    if (error.name === 'AbortError') return;
                    console.error('Error fetching autocomplete:', error);
                });
        }, AUTOCOMPLETE_DEBOUNCE_MS);
    });

    function updateAutocompleteHighlight(items) {
        items.forEach((item, index) => {
            item.classList.toggle('autocomplete-item-active', index === currentAutocompleteIndex);
        });
    }

    document.addEventListener('keydown', function(e) {
        const items = autocompleteDropdown
            ? autocompleteDropdown.querySelectorAll('.autocomplete-item')
            : [];
        if (items.length === 0) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                currentAutocompleteIndex = Math.min(currentAutocompleteIndex + 1, items.length - 1);
                updateAutocompleteHighlight(items);
                break;
            case 'ArrowUp':
                e.preventDefault();
                currentAutocompleteIndex = Math.max(currentAutocompleteIndex - 1, -1);
                updateAutocompleteHighlight(items);
                break;
            case 'Enter':
                if (currentAutocompleteIndex >= 0 && items[currentAutocompleteIndex]) {
                    e.preventDefault();
                    items[currentAutocompleteIndex].click();
                }
                break;
            case 'Escape':
                dismissAutocomplete();
                break;
        }
    });

    document.addEventListener('click', function(e) {
        if (searchInput.contains(e.target)) return;
        if (sampleStocksDropdown && !sampleStocksDropdown.contains(e.target)) {
            hideSampleStocksDropdown();
        }
        if (autocompleteDropdown && !autocompleteDropdown.contains(e.target)) {
            dismissAutocomplete();
        }
    });

    sentimentForm.addEventListener('submit', function(e) {
        e.preventDefault();
        analyze(searchInput.value);
    });

    document.querySelectorAll('.quick-pick').forEach(pick => {
        pick.addEventListener('click', function() {
            analyze(this.dataset.symbol);
        });
    });
});
