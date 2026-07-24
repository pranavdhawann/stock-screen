// Market Wire — market-aware general finance headlines feed (Track page).
//
// Standalone (only loads on /track via templates/track.html), so it
// duplicates the small news-item render helper rather than reaching into
// index-page.js. It reads the shared #marketSelect (owned by base.html /
// market-toggle.js) to know which market's headlines to show, and re-fetches
// whenever that select fires its native `change` event.
//
// The feed is paged client-side: the API returns the whole wire in one
// response, and this file reveals it PAGE_SIZE headlines at a time behind a
// LOAD MORE button so the page opens short.
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('marketWireContainer');
    if (!container) return;

    const updatedLabel = document.getElementById('marketWireUpdated');
    const moreRow = document.getElementById('marketWireMoreRow');
    const moreBtn = document.getElementById('marketWireMoreBtn');
    const marketSelect = document.getElementById('marketSelect');

    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeUrl = utils.sanitizeUrl || (() => '');
    const fetchJson = utils.fetchJson || ((url, options) => fetch(url, options).then(r => r.json()));
    const trackEvent = utils.trackEvent || (() => {});

    const PAGE_SIZE = 5;

    // Everything the API returned, plus how much of it is currently painted.
    let allItems = [];
    let shownCount = 0;

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
    function newsItemMarkup(item) {
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
    }

    function setMoreVisible(visible) {
        if (!moreRow) return;
        moreRow.classList.toggle('idx-hidden', !visible);
    }

    function showEmpty(message) {
        container.innerHTML = `<div class="text-center py-3 idx-news-empty">${escapeHtml(message)}</div>`;
        setMoreVisible(false);
    }

    // Appends the next page instead of re-rendering everything, so already
    // visible headlines don't flicker when LOAD MORE is pressed.
    function renderNextPage() {
        const next = allItems.slice(shownCount, shownCount + PAGE_SIZE);
        if (next.length === 0) {
            setMoreVisible(false);
            return;
        }
        container.insertAdjacentHTML('beforeend', next.map(newsItemMarkup).join(''));
        shownCount += next.length;
        setMoreVisible(shownCount < allItems.length);
    }

    function renderFirstPage(items) {
        allItems = Array.isArray(items) ? items : [];
        shownCount = 0;
        container.innerHTML = '';
        if (allItems.length === 0) {
            showEmpty('No headlines available right now.');
            return;
        }
        renderNextPage();
    }

    // Toggling markets fires a fetch per change, and those can resolve out of
    // order — a slow US response landing after a fast IN one would leave the
    // page showing headlines for the market that is no longer selected. Each
    // request takes a token and only the newest one is allowed to render.
    let requestToken = 0;

    function loadNews() {
        const token = ++requestToken;
        container.innerHTML = '<div class="text-center py-3"><span class="terminal-cursor">LOADING HEADLINES</span></div>';
        setMoreVisible(false);
        if (updatedLabel) updatedLabel.textContent = '';

        fetchJson(`/api/market_news?market=${getCurrentMarket()}`)
            .then(data => {
                if (requestToken !== token) return;
                renderFirstPage(data.news || []);
                updateTimestamp(data.fetched_at || null);
            })
            .catch(error => {
                if (requestToken !== token) return;
                console.error('[Market Wire] Fetch error:', error);
                showEmpty('Unable to load headlines. Please try again later.');
            });
    }

    if (moreBtn) {
        moreBtn.addEventListener('click', function() {
            trackEvent('market-wire-load-more', { shown: shownCount });
            renderNextPage();
        });
    }

    if (marketSelect) {
        marketSelect.addEventListener('change', loadNews);
    }

    loadNews();
});
