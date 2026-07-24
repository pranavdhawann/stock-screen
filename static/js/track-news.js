// Track News page — market-aware general finance headlines feed.
//
// Standalone (only loads on /track-news via templates/track_news.html), so
// it duplicates the small news-item render helper rather than reaching into
// index-page.js. It reads the shared #marketSelect (owned by base.html /
// market-toggle.js) to know which market's headlines to show, and re-fetches
// whenever that select fires its native `change` event.
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('trackNewsContainer');
    if (!container) return;

    const updatedLabel = document.getElementById('trackNewsUpdated');
    const marketSelect = document.getElementById('marketSelect');

    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeUrl = utils.sanitizeUrl || (() => '');
    const fetchJson = utils.fetchJson || ((url, options) => fetch(url, options).then(r => r.json()));
    const trackEvent = utils.trackEvent || (() => {});

    function getCurrentMarket() {
        return marketSelect && marketSelect.value === 'IN' ? 'IN' : 'US';
    }

    function updateTimestamp(fetchedAt) {
        if (!updatedLabel) return;
        if (!fetchedAt) { updatedLabel.textContent = ''; return; }
        // /api/market_news sends fetched_at as unix SECONDS; normalise to ms
        // the same way published timestamps are handled below.
        const raw = Number(fetchedAt);
        const ts = Number.isFinite(raw)
            ? (raw < 1e12 ? raw * 1000 : raw)
            : new Date(fetchedAt).getTime();
        if (!ts) { updatedLabel.textContent = ''; return; }
        const mins = Math.max(0, Math.floor((Date.now() - ts) / 60000));
        if (mins < 1) updatedLabel.textContent = 'Updated just now';
        else if (mins < 60) updatedLabel.textContent = `Updated ${mins}m ago`;
        else updatedLabel.textContent = `Updated ${Math.floor(mins / 60)}h ${mins % 60}m ago`;
    }

    // Same .news-item / .news-container markup conventions as the analysis
    // view's news renderer in index-page.js, so it inherits existing CSS.
    function renderNews(target, items, emptyMessage) {
        if (!target) return;
        if (!items || items.length === 0) {
            target.innerHTML = `<div class="text-center py-3 idx-news-empty">${escapeHtml(emptyMessage)}</div>`;
            return;
        }

        target.innerHTML = items.map(item => {
            const titleRaw = String(item?.title || '');
            const summaryRaw = String(item?.summary || '');
            const summaryTrimmed = summaryRaw.length > 200 ? `${summaryRaw.slice(0, 200)}...` : summaryRaw;
            const publisher = escapeHtml(item?.publisher || 'News');
            const published = Number(item?.published || 0);
            const publishedMs = published < 1e12 ? published * 1000 : published;
            const timeLabel = publishedMs ? new Date(publishedMs).toLocaleString('en-US', {
                month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
            }) : '--:--';
            const safeLink = sanitizeUrl(item?.link);

            return `
                <div class="news-item">
                    <div class="d-flex align-items-start gap-2">
                        <span class="idx-news-time">${escapeHtml(timeLabel)}</span>
                        <div class="flex-grow-1">
                            <div class="news-header-mobile mb-1">
                                ${safeLink ? `<a href="${safeLink}" target="_blank" rel="noopener noreferrer">${escapeHtml(titleRaw)}</a>` : escapeHtml(titleRaw)}
                            </div>
                            ${summaryTrimmed ? `<p class="news-snippet mb-1">${escapeHtml(summaryTrimmed)}</p>` : ''}
                            <div class="d-flex align-items-center gap-2">
                                <span class="publisher">${publisher}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Toggling markets fires a fetch per change, and those can resolve out of
    // order — a slow US response landing after a fast IN one would leave the
    // page showing headlines for the market that is no longer selected. Each
    // request takes a token and only the newest one is allowed to render.
    let requestToken = 0;

    function loadNews() {
        const token = ++requestToken;
        container.innerHTML = '<div class="text-center py-3"><span class="terminal-cursor">LOADING HEADLINES</span></div>';
        if (updatedLabel) updatedLabel.textContent = '';

        fetchJson(`/api/market_news?market=${getCurrentMarket()}`)
            .then(data => {
                if (requestToken !== token) return;
                renderNews(container, data.news || [], 'No headlines available right now.');
                updateTimestamp(data.fetched_at || null);
            })
            .catch(error => {
                if (requestToken !== token) return;
                console.error('[Track News] Fetch error:', error);
                container.innerHTML = '<div class="text-center py-3 idx-news-empty">Unable to load headlines. Please try again later.</div>';
            });
    }

    if (marketSelect) {
        marketSelect.addEventListener('change', loadNews);
    }

    loadNews();

    // ── Per-stock news ────────────────────────────────────────────────────
    // Same aggregated feed the analysis view shows (/api/news), given its own
    // ticker box here so the page stands alone: you can pull a stock's wire
    // without first running a full sentiment analysis on the main page.
    const stockForm = document.getElementById('stockNewsForm');
    const stockInput = document.getElementById('stockNewsInput');
    const stockContainer = document.getElementById('stockNewsContainer');

    if (stockForm && stockInput && stockContainer) {
        let stockToken = 0;

        // Survives navigation away and back, so the section isn't empty every
        // time you return to the page.
        const LAST_SYMBOL_KEY = 'trackNewsLastSymbol';

        function readLastSymbol() {
            try {
                return window.localStorage.getItem(LAST_SYMBOL_KEY) || '';
            } catch (e) {
                return '';
            }
        }

        function rememberSymbol(symbol) {
            try {
                window.localStorage.setItem(LAST_SYMBOL_KEY, symbol);
            } catch (e) {
                /* private mode / storage disabled - not worth failing over */
            }
        }

        function loadStockNews(symbol) {
            const token = ++stockToken;
            stockContainer.innerHTML =
                '<div class="text-center py-3"><span class="terminal-cursor">LOADING ' +
                escapeHtml(symbol) + ' NEWS</span></div>';

            fetchJson(`/api/news?symbol=${encodeURIComponent(symbol)}`)
                .then(data => {
                    if (stockToken !== token) return;
                    // Only remember symbols the API accepted, so a typo does
                    // not greet you with its own error on every later visit.
                    rememberSymbol(symbol);
                    renderNews(
                        stockContainer,
                        data.news_items || [],
                        `No recent news for ${symbol}.`,
                    );
                })
                .catch(error => {
                    if (stockToken !== token) return;
                    console.error('[Track News] Stock news error:', error);
                    stockContainer.innerHTML =
                        `<div class="text-center py-3 idx-news-empty">${escapeHtml(error.message || 'Unable to load news for that symbol.')}</div>`;
                });
        }

        stockForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const symbol = stockInput.value.trim().toUpperCase();
            if (!symbol) return;
            trackEvent('track-news-symbol', { symbol: symbol });
            loadStockNews(symbol);
        });

        const remembered = readLastSymbol();
        if (remembered) {
            stockInput.value = remembered;
            loadStockNews(remembered);
        } else {
            stockContainer.innerHTML =
                '<div class="text-center py-3 idx-news-empty">Enter a ticker above to load its news.</div>';
        }
    }
});
