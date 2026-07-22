// Landing-page market charts (default markets grid), the main price/sentiment
// chart, and the volume/liquidity + sentiment-timeline + technical-indicator
// trader panels shown on the stock analysis view.
//
// Split out of index-page.js. Exposes window.StockScreenCharts so the core
// script (search/autocomplete/analyze flow, still in index-page.js) can call
// into this module. Both files also need to read/write the latest
// /api/indicators payload, so it lives on window.StockScreenCharts.state
// instead of a private closure variable — that is the one piece of state
// that was shared across this split.
//
// Load order requirement: this file must be loaded BEFORE index-page.js,
// since index-page.js calls window.StockScreenCharts.* synchronously from
// its own DOMContentLoaded handler (e.g. from the market selector change
// handler and the chart-range toggle).
document.addEventListener('DOMContentLoaded', function() {
    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeSymbol = utils.sanitizeSymbol || (value => String(value ?? '').replace(/[^A-Za-z0-9.^-]/g, ''));
    const fetchJson = utils.fetchJson;

    window.StockScreenCharts = window.StockScreenCharts || {};
    window.StockScreenCharts.state = window.StockScreenCharts.state || { indicatorsData: null };

    // Establish the initial hidden state via CSSOM (equivalent to the
    // display:none these two elements used to carry as an inline style
    // attribute) so it stays compatible with the style.display = ''
    // reveal calls in renderTraderMetrics()/renderIndicatorPanel() below.
    const initialTraderMetricsPanel = document.getElementById('traderMetricsPanel');
    const initialTechnicalTogglePanel = document.getElementById('technicalTogglePanel');
    if (initialTraderMetricsPanel) initialTraderMetricsPanel.style.display = 'none';
    if (initialTechnicalTogglePanel) initialTechnicalTogglePanel.style.display = 'none';

    // Store the current symbol for chart range switching
    let volumeLiquidityChart = null;
    let sentimentTimelineChart = null;
    let indicatorMomentumChart = null;

    function compactNumber(value) {
        const number = Number(value || 0);
        return Intl.NumberFormat('en-US', {
            notation: 'compact',
            maximumFractionDigits: 1,
        }).format(number);
    }

    function activeIndicator(name) {
        const toggle = document.querySelector(`.indicator-toggle[value="${name}"]`);
        return !toggle || toggle.checked;
    }

    // Load default market data
    function loadDefaultMarkets(location = 'US') {
        const defaultMarketsContainer = document.getElementById('defaultMarketsContainer');
        const defaultMarketsSection = document.getElementById('defaultMarketsSection');

        if (!defaultMarketsContainer || !defaultMarketsSection) return;

        // Show loading state
        defaultMarketsContainer.innerHTML = `
            <div class="col-12 text-center py-3">
                <span class="terminal-cursor">LOADING MARKETS</span>
            </div>
        `;

        fetchJson(`/api/get_default_markets?location=${location}`)
            .then(data => {
                displayDefaultMarkets(data.markets);
            })
            .catch(error => {
                console.error('Error loading default markets:', error);
                defaultMarketsContainer.innerHTML = `
                    <div class="col-12 text-center py-2">
                        <span class="terminal-cursor idx-markets-error">ERROR: MARKET DATA UNAVAILABLE</span>
                    </div>
                `;
            });
    }

    // Display default market data
    function displayDefaultMarkets(markets) {
        const defaultMarketsContainer = document.getElementById('defaultMarketsContainer');

        if (!defaultMarketsContainer || !markets || markets.length === 0) return;

        const marketsHtml = markets.map(market => {
            const isPositive = Number(market.price_change || 0) >= 0;
            const changeClass = isPositive ? 'text-success' : 'text-danger';
            const safeSymbol = sanitizeSymbol(market.symbol);
            const safeCurrency = escapeHtml(market.currency || '$');
            const currentPrice = Number(market.current_price || 0);
            const priceChange = Number(market.price_change || 0);
            const priceChangePercent = Number(market.price_change_percent || 0);

            // Dense terminal stats from the chart data already in hand.
            const chartData = Array.isArray(market.chart_data) ? market.chart_data : [];
            const last = chartData[chartData.length - 1] || {};
            const highs = chartData.map(p => Number(p.high)).filter(Number.isFinite);
            const lows = chartData.map(p => Number(p.low)).filter(Number.isFinite);
            const fmt = value => Number.isFinite(Number(value)) && value !== null
                ? Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 })
                : '—';
            const statsHtml = chartData.length ? `
                <div class="market-stats-row">
                    <span class="market-stat"><span class="market-stat-label">OPEN</span>${safeCurrency}${fmt(last.open)}</span>
                    <span class="market-stat"><span class="market-stat-label">HI</span>${safeCurrency}${fmt(last.high)}</span>
                    <span class="market-stat"><span class="market-stat-label">LO</span>${safeCurrency}${fmt(last.low)}</span>
                    <span class="market-stat"><span class="market-stat-label">30D RNG</span>${safeCurrency}${fmt(lows.length ? Math.min(...lows) : null)}–${safeCurrency}${fmt(highs.length ? Math.max(...highs) : null)}</span>
                    <span class="market-stat"><span class="market-stat-label">VOL</span>${compactNumber(last.volume || 0)}</span>
                </div>` : '';

            return `
                <div class="market-card">
                    <div class="card-body">
                        <h5 class="card-title">${escapeHtml(market.display_name)}</h5>
                        <div class="market-price">
                            <div class="price-value">${safeCurrency}${currentPrice.toLocaleString()}</div>
                            <div class="price-change ${changeClass}">

                                ${safeCurrency}${Math.abs(priceChange).toFixed(2)} (${Math.abs(priceChangePercent).toFixed(2)}%)
                            </div>
                        </div>
                        ${statsHtml}
                        <div class="market-chart" data-display-name="${escapeHtml(market.display_name)}">
                            <canvas id="chart-${safeSymbol.replace(/[^a-zA-Z0-9]/g, '')}" width="500" height="350"></canvas>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        defaultMarketsContainer.innerHTML = marketsHtml;

        // Create charts for each market
        markets.forEach(market => {
            createMarketChart(market);
        });

        // Add click functionality to expand charts
        addChartExpansionFunctionality();
    }

    // Create chart for market data
    function createMarketChart(market) {
        const canvasId = `chart-${market.symbol.replace(/[^a-zA-Z0-9]/g, '')}`;
        const canvas = document.getElementById(canvasId);

        if (!canvas || !market.chart_data || market.chart_data.length === 0) return;

        const ctx = canvas.getContext('2d');

        const chartData = market.chart_data.map(item => ({
            x: new Date(item.date),
            y: item.price
        }));

        // Determine chart color based on price movement
        let chartColor = '#FFA500'; // Default amber
        let bgColor = 'rgba(255, 165, 0, 0.05)';

        if (chartData.length >= 2) {
            const latestClose = chartData[chartData.length - 1].y;
            const previousClose = chartData[chartData.length - 2].y;

            if (latestClose >= previousClose) {
                chartColor = '#00FF88';
                bgColor = 'rgba(0, 255, 136, 0.05)';
            } else {
                chartColor = '#FF3B3B';
                bgColor = 'rgba(255, 59, 59, 0.05)';
            }
        }

        try {
            new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: market.display_name,
                        data: chartData,
                        borderColor: chartColor,
                        backgroundColor: bgColor,
                        borderWidth: 1.5,
                        tension: 0.1,
                        fill: true,
                        pointRadius: 3,
                        pointBackgroundColor: chartColor,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: chartColor,
                        pointHoverBorderColor: '#0a0a0a',
                        pointHoverBorderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false,
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'day',
                                displayFormats: { day: 'MMM dd' }
                            },
                            display: true,
                            grid: { color: 'rgba(42, 45, 53, 0.5)' },
                            ticks: {
                                color: '#666',
                                font: { size: 10, family: "'JetBrains Mono', monospace" },
                                maxTicksLimit: 6
                            }
                        },
                        y: {
                            display: true,
                            position: 'right',
                            grid: {
                                color: 'rgba(42, 45, 53, 0.5)',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#666',
                                font: { size: 10, family: "'JetBrains Mono', monospace" },
                                maxTicksLimit: 5,
                                callback: function(value) {
                                    return market.currency + value.toLocaleString();
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            enabled: true,
                            backgroundColor: '#0f1117',
                            titleColor: '#FFA500',
                            bodyColor: '#E8E8E8',
                            borderColor: '#2a2d35',
                            borderWidth: 1,
                            cornerRadius: 0,
                            displayColors: false,
                            titleFont: { size: 11, weight: 'bold', family: "'JetBrains Mono', monospace" },
                            bodyFont: { size: 11, family: "'JetBrains Mono', monospace" },
                            callbacks: {
                                title: function(context) { return market.display_name; },
                                label: function(context) {
                                    return `${market.currency}${context.parsed.y.toLocaleString()}`;
                                }
                            }
                        }
                    }
                }
            });
        } catch (error) {
            console.error('Error creating market chart:', error);
        }
    }

    // Add chart expansion functionality
    function addChartExpansionFunctionality() {
        const marketCharts = document.querySelectorAll('.market-chart');

        marketCharts.forEach(chart => {
            if (chart.dataset.expandBound === '1') {
                return;
            }
            chart.dataset.expandBound = '1';

            chart.addEventListener('click', function() {
                const canvas = this.querySelector('canvas');
                if (!canvas) return;

                // Prefer the stored display name; fall back to the canvas ID.
                const marketName = this.dataset.displayName
                    || canvas.id.replace('chart-', '');

                // Create modal for expanded chart
                const modal = document.createElement('div');
                modal.className = 'chart-modal';
                modal.innerHTML = `
                    <div class="chart-modal-content">
                        <div class="chart-modal-header">
                            <h5>${escapeHtml(marketName)} - Expanded View</h5>
                            <button class="chart-modal-close">&times;</button>
                        </div>
                        <div class="chart-modal-body">
                            <canvas id="expanded-${canvas.id}" width="800" height="400"></canvas>
                        </div>
                    </div>
                `;

                document.body.appendChild(modal);
                // Trigger reflow, then add active class for transition
                modal.offsetHeight;
                modal.classList.add('active');

                // Get original chart instance and recreate with larger size
                const originalChart = Chart.getChart(canvas);
                if (originalChart) {
                    const expandedCanvas = document.getElementById(`expanded-${canvas.id}`);
                    const expandedCtx = expandedCanvas.getContext('2d');

                    // Clone the chart data
                    const chartData = JSON.parse(JSON.stringify(originalChart.data));
                    const chartOptions = JSON.parse(JSON.stringify(originalChart.options));

                    // Update options for expanded view
                    chartOptions.responsive = true;
                    chartOptions.maintainAspectRatio = false;
                    chartOptions.scales.x.display = true;
                    chartOptions.scales.y.display = true;
                    chartOptions.plugins.legend.display = true;
                    chartOptions.plugins.tooltip.enabled = true;

                    // Create new chart instance
                    new Chart(expandedCtx, {
                        type: originalChart.config.type,
                        data: chartData,
                        options: chartOptions
                    });
                }

                // Close modal functionality
                let isClosed = false;
                const onEscape = function(e) {
                    if (e.key === 'Escape') {
                        closeMarketModal();
                    }
                };

                function closeMarketModal() {
                    if (isClosed) return;
                    isClosed = true;

                    const expandedCanvas = document.getElementById(`expanded-${canvas.id}`);
                    if (expandedCanvas) {
                        const expandedChart = Chart.getChart(expandedCanvas);
                        if (expandedChart) expandedChart.destroy();
                    }
                    document.removeEventListener('keydown', onEscape);
                    if (modal.parentNode) {
                        document.body.removeChild(modal);
                    }
                }

                modal.querySelector('.chart-modal-close').addEventListener('click', closeMarketModal);
                modal.addEventListener('click', (e) => { if (e.target === modal) closeMarketModal(); });
                document.addEventListener('keydown', onEscape);
            });
        });
    }

    function renderVolumeLiquidity(data) {
        const canvas = document.getElementById('volumeLiquidityChart');
        const summary = document.getElementById('volumeSummary');
        if (!canvas || typeof Chart === 'undefined' || !Array.isArray(data?.chart_data)) return;

        if (volumeLiquidityChart) {
            volumeLiquidityChart.destroy();
        }

        const bars = data.chart_data.map((item, index) => {
            const close = Number(item.price || item.close || 0);
            const open = Number(item.open || close);
            return {
                x: new Date(item.date),
                y: Number(data.volume?.[index] ?? item.volume ?? 0),
                backgroundColor: close >= open ? 'rgba(0, 255, 136, 0.45)' : 'rgba(255, 59, 59, 0.45)',
            };
        });
        const relativeVolume = data.chart_data.map((item, index) => ({
            x: new Date(item.date),
            y: Number(data.relative_volume?.[index] || 0),
        }));

        volumeLiquidityChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                datasets: [
                    {
                        label: 'Volume',
                        data: bars,
                        backgroundColor: bars.map(item => item.backgroundColor),
                        borderWidth: 0,
                        yAxisID: 'y',
                    },
                    {
                        type: 'line',
                        label: 'Relative volume',
                        data: relativeVolume,
                        borderColor: '#00D4FF',
                        backgroundColor: 'rgba(0, 212, 255, 0.12)',
                        pointRadius: 0,
                        borderWidth: 1.5,
                        tension: 0.2,
                        yAxisID: 'y1',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: { type: 'time', time: { unit: 'day' }, ticks: { color: '#666', maxTicksLimit: 4 }, grid: { display: false } },
                    y: { ticks: { color: '#666', callback: compactNumber }, grid: { color: 'rgba(42,45,53,0.45)' } },
                    y1: { position: 'right', ticks: { color: '#00D4FF' }, grid: { drawOnChartArea: false } },
                },
            },
        });

        if (summary) {
            const lastIndex = Math.max((data.chart_data || []).length - 1, 0);
            const rel = Number(data.relative_volume?.[lastIndex] || 0).toFixed(2);
            const dollars = compactNumber(data.dollar_volume?.[lastIndex] || 0);
            const spike = data.volume_spike?.[lastIndex] ? 'spike' : 'normal';
            summary.textContent = `Last volume ${compactNumber(data.volume?.[lastIndex] || 0)} | ${rel}x average | ${data.currency || '$'}${dollars} traded | ${spike}`;
        }
    }

    function renderSentimentTimeline(data) {
        const canvas = document.getElementById('sentimentTimelineChart');
        const summary = document.getElementById('sentimentDivergence');
        const timeline = data?.sentiment_timeline || [];
        if (!canvas || typeof Chart === 'undefined' || !Array.isArray(timeline)) return;

        if (sentimentTimelineChart) {
            sentimentTimelineChart.destroy();
        }

        const scoreData = timeline.map(item => ({ x: new Date(item.date), y: Number(item.score || 0) }));
        const countData = timeline.map(item => ({ x: new Date(item.date), y: Number(item.headline_count || 0) }));

        sentimentTimelineChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'Sentiment score',
                        data: scoreData,
                        borderColor: '#FFA500',
                        backgroundColor: 'rgba(255, 165, 0, 0.12)',
                        borderWidth: 1.5,
                        pointRadius: 2,
                        tension: 0.25,
                        fill: true,
                    },
                    {
                        type: 'bar',
                        label: 'Headlines',
                        data: countData,
                        backgroundColor: 'rgba(0, 212, 255, 0.28)',
                        borderWidth: 0,
                        yAxisID: 'y1',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { type: 'time', time: { unit: 'day' }, ticks: { color: '#666', maxTicksLimit: 4 }, grid: { display: false } },
                    y: { min: -1, max: 1, ticks: { color: '#666' }, grid: { color: 'rgba(42,45,53,0.45)' } },
                    y1: { position: 'right', min: 0, ticks: { color: '#00D4FF', precision: 0 }, grid: { drawOnChartArea: false } },
                },
            },
        });

        if (summary) {
            const divergence = Number(data.sentiment_divergence || 0);
            const label = divergence > 0.25 ? 'price/sentiment divergence' : divergence < -0.25 ? 'price confirms sentiment' : 'mixed confirmation';
            summary.textContent = `Divergence ${divergence.toFixed(2)} | ${label}`;
        }
    }

    function renderIndicatorPanel(indicatorPayload) {
        const panel = document.getElementById('traderMetricsPanel');
        const togglePanel = document.getElementById('technicalTogglePanel');
        const summary = document.getElementById('indicatorSummary');
        const canvas = document.getElementById('indicatorMomentumChart');
        const rows = indicatorPayload?.indicators || [];
        if (panel) panel.style.display = '';
        if (togglePanel) togglePanel.style.display = '';
        if (!rows.length || !canvas || typeof Chart === 'undefined') {
            if (summary) summary.textContent = 'Indicators unavailable for the current series.';
            return;
        }

        if (indicatorMomentumChart) {
            indicatorMomentumChart.destroy();
        }

        const latest = indicatorPayload.latest || rows[rows.length - 1] || {};
        if (summary) {
            summary.innerHTML = [
                `RSI 14: <span class="idx-indicator-value">${Number(latest.rsi_14 || 0).toFixed(1)}</span>`,
                `MACD: <span class="idx-indicator-value">${Number(latest.macd || 0).toFixed(2)}</span>`,
                `ATR 14: <span class="idx-indicator-value">${Number(latest.atr_14 || 0).toFixed(2)}</span>`,
                `Volume ratio: <span class="idx-indicator-value">${Number(latest.volume_ratio || 0).toFixed(2)}x</span>`,
            ].join('<br>');
        }

        indicatorMomentumChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'RSI 14',
                        data: rows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.rsi_14 || 0) })),
                        borderColor: '#00D4FF',
                        backgroundColor: 'rgba(0, 212, 255, 0.08)',
                        yAxisID: 'y',
                        pointRadius: 0,
                        borderWidth: 1.5,
                    },
                    {
                        type: 'bar',
                        label: 'MACD histogram',
                        data: rows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.macd_histogram || 0) })),
                        backgroundColor: rows.map(item => Number(item.macd_histogram || 0) >= 0 ? 'rgba(0,255,136,0.35)' : 'rgba(255,59,59,0.35)'),
                        yAxisID: 'y1',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { type: 'time', time: { unit: 'day' }, ticks: { color: '#666', maxTicksLimit: 4 }, grid: { display: false } },
                    y: { min: 0, max: 100, ticks: { color: '#00D4FF' }, grid: { color: 'rgba(42,45,53,0.45)' } },
                    y1: { position: 'right', ticks: { color: '#FFA500' }, grid: { drawOnChartArea: false } },
                },
            },
        });
    }

    function renderTraderMetrics(data, indicatorPayload = window.StockScreenCharts.state.indicatorsData) {
        const panel = document.getElementById('traderMetricsPanel');
        const togglePanel = document.getElementById('technicalTogglePanel');
        if (panel) panel.style.display = '';
        if (togglePanel) togglePanel.style.display = '';
        renderVolumeLiquidity(data);
        renderSentimentTimeline(data);
        renderIndicatorPanel(indicatorPayload);
    }

    // Create price-sentiment overlay chart
    function createPriceSentimentChart(data) {
        const canvas = document.getElementById('priceSentimentChart');
        if (!canvas || !Array.isArray(data.chart_data)) return;

        // Destroy existing chart if it exists
        if (window.priceSentimentChartInstance) {
            window.priceSentimentChartInstance.destroy();
            window.priceSentimentChartInstance = null;
        }

        const ctx = canvas.getContext('2d');

        const chartData = data.chart_data.map(item => ({
            x: new Date(item.date),
            y: Number(item.price || item.close || 0)
        }));
        const chartCurrency = data.currency || '$';
        const datasets = [];

        // Determine chart color based ONLY on stock movement (latest vs previous close)
        let chartColor = '#FFA500'; // Default amber
        let backgroundColor = 'rgba(255, 165, 0, 0.05)';

        // Calculate stock movement from latest close vs previous close
        if (chartData.length >= 2) {
            const latestClose = chartData[chartData.length - 1].y;
            const previousClose = chartData[chartData.length - 2].y;

            if (latestClose >= previousClose) {
                chartColor = '#00FF88';
                backgroundColor = 'rgba(0, 255, 136, 0.05)';
            } else {
                chartColor = '#FF3B3B';
                backgroundColor = 'rgba(255, 59, 59, 0.05)';
            }
        }

        datasets.push({
            label: `Price (${chartCurrency})`,
            data: chartData,
            borderColor: chartColor,
            backgroundColor: backgroundColor,
            borderWidth: 1.5,
            tension: 0.1,
            fill: true,
            pointRadius: 2,
            pointBackgroundColor: chartColor,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: chartColor,
            pointHoverBorderColor: '#0a0a0a',
            pointHoverBorderWidth: 2,
            yAxisID: 'y',
        });

        const indicatorRows = window.StockScreenCharts.state.indicatorsData?.indicators || [];
        if (indicatorRows.length) {
            if (activeIndicator('sma_20')) {
                datasets.push({
                    label: 'SMA 20',
                    data: indicatorRows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.sma_20 || 0) })),
                    borderColor: '#00D4FF',
                    borderWidth: 1,
                    pointRadius: 0,
                    tension: 0.1,
                    yAxisID: 'y',
                });
            }
            if (activeIndicator('ema_20')) {
                datasets.push({
                    label: 'EMA 20',
                    data: indicatorRows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.ema_20 || 0) })),
                    borderColor: '#D6D6D6',
                    borderDash: [4, 3],
                    borderWidth: 1,
                    pointRadius: 0,
                    tension: 0.1,
                    yAxisID: 'y',
                });
            }
            if (activeIndicator('bb')) {
                datasets.push({
                    label: 'Bollinger upper',
                    data: indicatorRows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.bb_upper_20 || 0) })),
                    borderColor: 'rgba(255, 165, 0, 0.45)',
                    borderWidth: 1,
                    pointRadius: 0,
                    fill: false,
                    yAxisID: 'y',
                });
                datasets.push({
                    label: 'Bollinger lower',
                    data: indicatorRows.map(item => ({ x: new Date(item.timestamp || item.date), y: Number(item.bb_lower_20 || 0) })),
                    borderColor: 'rgba(255, 165, 0, 0.45)',
                    borderWidth: 1,
                    pointRadius: 0,
                    fill: false,
                    yAxisID: 'y',
                });
            }
        }

        if (activeIndicator('sentiment') && Array.isArray(data.sentiment_timeline) && data.sentiment_timeline.length) {
            datasets.push({
                type: 'bar',
                label: 'Sentiment score',
                data: data.sentiment_timeline.map(item => ({ x: new Date(item.date), y: Number(item.score || 0) })),
                backgroundColor: data.sentiment_timeline.map(item => Number(item.score || 0) >= 0
                    ? 'rgba(0, 255, 136, 0.22)'
                    : 'rgba(255, 59, 59, 0.22)'),
                borderWidth: 0,
                yAxisID: 'sentiment',
            });
        }

        try {
            window.priceSentimentChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day',
                            displayFormats: { day: 'MMM dd' }
                        },
                        title: { display: false },
                        ticks: {
                            color: '#666',
                            font: { family: "'JetBrains Mono', monospace", size: 10 },
                            maxTicksLimit: 8
                        },
                        grid: { color: 'rgba(42, 45, 53, 0.5)' }
                    },
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: false },
                        ticks: {
                            color: '#666',
                            font: { family: "'JetBrains Mono', monospace", size: 10 },
                            callback: function(value) {
                                return chartCurrency + value.toLocaleString();
                            }
                        },
                        grid: { color: 'rgba(42, 45, 53, 0.5)' }
                    },
                    sentiment: {
                        type: 'linear',
                        display: activeIndicator('sentiment'),
                        min: -1,
                        max: 1,
                        position: 'left',
                        ticks: {
                            color: '#999',
                            font: { family: "'JetBrains Mono', monospace", size: 10 },
                        },
                        grid: { drawOnChartArea: false }
                    }
                },
                plugins: {
                    legend: {
                        display: datasets.length > 1,
                        labels: {
                            color: '#999',
                            font: { family: "'JetBrains Mono', monospace", size: 10 },
                        },
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: '#0f1117',
                        titleColor: '#FFA500',
                        bodyColor: '#E8E8E8',
                        borderColor: '#2a2d35',
                        borderWidth: 1,
                        cornerRadius: 0,
                        titleFont: { family: "'JetBrains Mono', monospace", size: 11 },
                        bodyFont: { family: "'JetBrains Mono', monospace", size: 11 }
                    }
                }
            }
        });
        } catch (error) {
            console.error('Error creating chart:', error);
        }

        // Add expandable functionality to the main stock chart
        addStockChartExpansionFunctionality();
    }

    // Add expandable functionality to the main stock chart
    function addStockChartExpansionFunctionality() {
        const chartContainer = document.querySelector('.chart-container');
        if (!chartContainer) return;
        if (chartContainer.dataset.expandBound === '1') return;
        chartContainer.dataset.expandBound = '1';

        chartContainer.addEventListener('click', function() {
            const canvas = this.querySelector('canvas');
            if (!canvas) return;

            // Get the stock symbol from the search input
            const stockSymbol = document.getElementById('stockSearch').value || 'Stock';
            const safeStockSymbol = escapeHtml(stockSymbol);

            // Create modal for expanded chart
            const modal = document.createElement('div');
            modal.className = 'chart-modal';
            modal.innerHTML = `
                <div class="chart-modal-content">
                    <div class="chart-modal-header">
                        <h5>${safeStockSymbol} - Price Chart (Expanded View)</h5>
                        <button class="chart-modal-close">&times;</button>
                    </div>
                    <div class="chart-modal-body">
                        <canvas id="expanded-priceSentimentChart" width="800" height="500"></canvas>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            // Trigger reflow, then add active class for transition
            modal.offsetHeight;
            modal.classList.add('active');

            // Get original chart instance and recreate with larger size
            const originalChart = window.priceSentimentChartInstance;
            if (originalChart) {
                const expandedCanvas = document.getElementById('expanded-priceSentimentChart');
                const expandedCtx = expandedCanvas.getContext('2d');

                // Clone the chart data
                const chartData = JSON.parse(JSON.stringify(originalChart.data));
                const chartOptions = JSON.parse(JSON.stringify(originalChart.options));

                // Update options for expanded view
                chartOptions.responsive = true;
                chartOptions.maintainAspectRatio = false;
                chartOptions.scales.x.display = true;
                chartOptions.scales.y.display = true;
                chartOptions.plugins.legend.display = true;
                chartOptions.plugins.tooltip.enabled = true;

                // Create new chart instance
                new Chart(expandedCtx, {
                    type: originalChart.config.type,
                    data: chartData,
                    options: chartOptions
                });
            }

            // Close modal functionality
            let isClosed = false;
            const onEscape = function(e) {
                if (e.key === 'Escape') {
                    closeStockModal();
                }
            };

            function closeStockModal() {
                if (isClosed) return;
                isClosed = true;

                const expandedCanvas = document.getElementById('expanded-priceSentimentChart');
                if (expandedCanvas) {
                    const expandedChart = Chart.getChart(expandedCanvas);
                    if (expandedChart) expandedChart.destroy();
                }
                document.removeEventListener('keydown', onEscape);
                if (modal.parentNode) {
                    document.body.removeChild(modal);
                }
            }

            modal.querySelector('.chart-modal-close').addEventListener('click', closeStockModal);
            modal.addEventListener('click', (e) => { if (e.target === modal) closeStockModal(); });
            document.addEventListener('keydown', onEscape);
        });

        // Show expand icon on hover
        chartContainer.addEventListener('mouseenter', function() {
            const overlay = this.querySelector('.chart-expand-overlay');
            if (overlay) {
                overlay.style.opacity = '1';
            }
        });

        chartContainer.addEventListener('mouseleave', function() {
            const overlay = this.querySelector('.chart-expand-overlay');
            if (overlay) {
                overlay.style.opacity = '0';
            }
        });
    }

    window.StockScreenCharts.loadDefaultMarkets = loadDefaultMarkets;
    window.StockScreenCharts.createPriceSentimentChart = createPriceSentimentChart;
    window.StockScreenCharts.renderTraderMetrics = renderTraderMetrics;
    window.StockScreenCharts.renderIndicatorPanel = renderIndicatorPanel;

    // Load default market data on page load (US markets by default).
    // Relocated here (from index-page.js) alongside the function it calls —
    // this was already an async, side-effect-only call (fetchJson under the
    // hood) with no ordering dependency on the rest of index-page.js's init.
    loadDefaultMarkets('US');
});
