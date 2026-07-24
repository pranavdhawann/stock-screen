// Terminal extras on the markets landing tab: world clocks, the scrolling
// ticker tape, and the market-movers table (with per-row sparklines).
//
// Split out of index-page.js. The only external dependency is the analyze
// flow itself (still in index-page.js) — clicking a tape item or a movers
// row opens that symbol's analysis view. index-page.js already exposes that
// as window.StockScreenAnalyze (the same handle watchlist.js uses), so this
// module calls through that instead of a direct closure reference.
document.addEventListener('DOMContentLoaded', function() {
    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeSymbol = utils.sanitizeSymbol || (value => String(value ?? '').replace(/[^A-Za-z0-9.^-]/g, ''));
    const fetchJson = utils.fetchJson;

    function compactNumber(value) {
        const number = Number(value || 0);
        return Intl.NumberFormat('en-US', {
            notation: 'compact',
            maximumFractionDigits: 1,
        }).format(number);
    }

    const TAPE_SYMBOLS_BY_MARKET = {
        US: ['^GSPC', '^DJI', 'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'JPM', 'NFLX', 'V'],
        IN: ['^NSEI', '^BSESN', 'TCS', 'INFY', 'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'ITC', 'BHARTIARTL', 'MARUTI', 'TATAPOWER'],
    };
    const QUOTES_REFRESH_MS = 60 * 1000;

    // Shared current-market state (set by index-page.js's #marketSelect
    // change handler). Fall back to reading the select directly so a plain
    // page reload picks up the right market even before that handler runs.
    function getCurrentMarket() {
        const marketSelect = document.getElementById('marketSelect');
        if (marketSelect) {
            return marketSelect.value === 'IN' ? 'IN' : 'US';
        }
        return window.StockScreenMarket === 'IN' ? 'IN' : 'US';
    }

    function initTerminalClocks() {
        const zones = [
            { id: 'clockUSA', tz: 'America/New_York' },
            { id: 'clockIndia', tz: 'Asia/Kolkata' },
        ];
        const formatters = zones.map(zone => ({
            el: document.getElementById(zone.id),
            fmt: new Intl.DateTimeFormat('en-GB', {
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false, timeZone: zone.tz,
            }),
        })).filter(zone => zone.el);

        if (formatters.length === 0) return;

        function tick() {
            const now = new Date();
            formatters.forEach(zone => { zone.el.textContent = zone.fmt.format(now); });
        }
        tick();
        setInterval(tick, 1000);
    }

    function tapeEntryHtml(quote) {
        const pct = Number(quote.change_percent || 0);
        const dirClass = pct >= 0 ? 'tape-up' : 'tape-down';
        const arrow = pct >= 0 ? '▲' : '▼';
        const price = Number(quote.price || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });
        return `
            <span class="ticker-item ${dirClass}" data-symbol="${sanitizeSymbol(quote.symbol)}">
                <span class="ticker-symbol">${escapeHtml(quote.symbol)}</span>
                <span class="ticker-price">${escapeHtml(quote.currency || '$')}${price}</span>
                <span class="ticker-change">${arrow} ${Math.abs(pct).toFixed(2)}%</span>
            </span>`;
    }

    function renderTickerTape(quotes) {
        const track = document.getElementById('tickerTrack');
        if (!track || !quotes.length) return;

        const entries = quotes.map(tapeEntryHtml).join('<span class="ticker-divider">|</span>');
        // Duplicate the run once so the CSS -50% translate loops seamlessly.
        track.innerHTML = `<span class="ticker-run">${entries}<span class="ticker-divider">|</span></span>`
            + `<span class="ticker-run" aria-hidden="true">${entries}<span class="ticker-divider">|</span></span>`;

        track.querySelectorAll('.ticker-item').forEach(item => {
            item.addEventListener('click', function() {
                const symbol = this.dataset.symbol;
                if (symbol && !symbol.startsWith('^')) {
                    window.StockScreenAnalyze(symbol);
                }
            });
        });
    }

    function drawSparkline(canvas, series, positive) {
        if (!canvas || !Array.isArray(series) || series.length < 2) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const min = Math.min(...series);
        const max = Math.max(...series);
        const span = max - min || 1;
        const stepX = w / (series.length - 1);
        const pad = 2;

        ctx.clearRect(0, 0, w, h);
        ctx.beginPath();
        series.forEach((value, idx) => {
            const x = idx * stepX;
            const y = pad + (1 - (value - min) / span) * (h - pad * 2);
            if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = positive ? '#00FF88' : '#FF3B3B';
        ctx.lineWidth = 1.2;
        ctx.stroke();
    }

    function renderMoversTable(quotes) {
        const body = document.getElementById('moversTableBody');
        if (!body) return;

        const stocks = quotes
            .filter(quote => !String(quote.symbol || '').startsWith('^'))
            .sort((a, b) => Math.abs(Number(b.change_percent || 0)) - Math.abs(Number(a.change_percent || 0)));

        if (stocks.length === 0) {
            body.innerHTML = '<tr><td colspan="9" class="text-center py-3 idx-terminal-muted">NO QUOTE DATA</td></tr>';
            return;
        }

        body.innerHTML = stocks.map((quote, idx) => {
            const pct = Number(quote.change_percent || 0);
            const chg = Number(quote.change || 0);
            const dirClass = pct >= 0 ? 'mover-up' : 'mover-down';
            const sign = pct >= 0 ? '+' : '-';
            const cur = escapeHtml(quote.currency || '$');
            const fmt = value => value === null || value === undefined
                ? '—'
                : Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
            return `
                <tr class="mover-row" data-symbol="${sanitizeSymbol(quote.symbol)}">
                    <td class="mover-symbol">${escapeHtml(quote.symbol)}</td>
                    <td class="movers-name">${escapeHtml(quote.name || '')}</td>
                    <td class="movers-spark"><canvas id="spark-${idx}" width="64" height="20"></canvas></td>
                    <td class="text-end">${cur}${fmt(quote.price)}</td>
                    <td class="text-end ${dirClass}">${sign}${cur}${fmt(Math.abs(chg))}</td>
                    <td class="text-end ${dirClass}">${sign}${Math.abs(pct).toFixed(2)}%</td>
                    <td class="text-end movers-extra">${cur}${fmt(quote.day_high)}</td>
                    <td class="text-end movers-extra">${cur}${fmt(quote.day_low)}</td>
                    <td class="text-end movers-extra">${compactNumber(quote.volume)}</td>
                </tr>`;
        }).join('');

        stocks.forEach((quote, idx) => {
            drawSparkline(
                document.getElementById(`spark-${idx}`),
                quote.spark,
                Number(quote.change_percent || 0) >= 0
            );
        });

        body.querySelectorAll('.mover-row').forEach(row => {
            row.addEventListener('click', function() {
                const symbol = this.dataset.symbol;
                if (symbol) window.StockScreenAnalyze(symbol);
            });
        });
    }

    function loadTerminalQuotes() {
        const market = getCurrentMarket();
        const tapeSymbols = TAPE_SYMBOLS_BY_MARKET[market] || TAPE_SYMBOLS_BY_MARKET.US;
        fetchJson(`/api/quotes?symbols=${encodeURIComponent(tapeSymbols.join(','))}`)
            .then(data => {
                const quotes = data.quotes || [];
                renderTickerTape(quotes);
                renderMoversTable(quotes);
                const label = document.getElementById('moversLastUpdated');
                if (label && data.timestamp) {
                    const time = new Date(data.timestamp).toLocaleTimeString('en-GB', { hour12: false });
                    label.textContent = `AS OF ${time}`;
                }
            })
            .catch(error => {
                console.error('Error loading terminal quotes:', error);
                const track = document.getElementById('tickerTrack');
                if (track) {
                    track.innerHTML = '<span class="ticker-loading idx-terminal-error">TAPE UNAVAILABLE</span>';
                }
                const body = document.getElementById('moversTableBody');
                if (body) {
                    body.innerHTML = '<tr><td colspan="9" class="text-center py-3 idx-terminal-muted">QUOTES UNAVAILABLE</td></tr>';
                }
            });
    }

    // Exposed so index-page.js can trigger an immediate refresh when the
    // market toggle changes, following the same convention as
    // window.StockScreenCharts (see index-charts.js).
    window.StockScreenTerminal = window.StockScreenTerminal || {};
    window.StockScreenTerminal.loadTerminalQuotes = loadTerminalQuotes;

    initTerminalClocks();
    loadTerminalQuotes();
    // Re-reads the current market every tick via loadTerminalQuotes/getCurrentMarket.
    setInterval(loadTerminalQuotes, QUOTES_REFRESH_MS);
});
