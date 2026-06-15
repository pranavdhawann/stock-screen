document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('stockSearch');
    const autocompleteDropdown = document.getElementById('autocompleteDropdown');
    const sampleStocksDropdown = document.getElementById('sampleStocksDropdown');
    const sentimentForm = document.getElementById('sentimentForm');
    const resultsSection = document.getElementById('resultsSection');
    const progressSection = document.getElementById('progressSection');
    const errorMessage = document.getElementById('errorMessage');
    const stockPageTitle = document.getElementById('stockPageTitle');
    const backToMarketsBtn = document.getElementById('backToMarketsBtn');
    
    let searchTimeout;
    let currentAutocompleteIndex = -1;
    const AUTOCOMPLETE_DEBOUNCE_MS = 150;

    // Helper: hide autocomplete dropdown and reset keyboard index
    function dismissAutocomplete() {
        if (autocompleteDropdown) {
            autocompleteDropdown.style.display = 'none';
        }
        currentAutocompleteIndex = -1;
    }

    // Keyboard navigation for autocomplete
    document.addEventListener('keydown', function(e) {
        const autocompleteItems = document.querySelectorAll('.autocomplete-item');
        if (autocompleteItems.length === 0) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                currentAutocompleteIndex = Math.min(currentAutocompleteIndex + 1, autocompleteItems.length - 1);
                updateAutocompleteHighlight(autocompleteItems);
                break;
            case 'ArrowUp':
                e.preventDefault();
                currentAutocompleteIndex = Math.max(currentAutocompleteIndex - 1, -1);
                updateAutocompleteHighlight(autocompleteItems);
                break;
            case 'Enter':
                e.preventDefault();
                if (currentAutocompleteIndex >= 0 && autocompleteItems[currentAutocompleteIndex]) {
                    autocompleteItems[currentAutocompleteIndex].click();
                }
                break;
            case 'Escape':
                dismissAutocomplete();
                break;
        }
    });

    function updateAutocompleteHighlight(items) {
        items.forEach((item, index) => {
            if (index === currentAutocompleteIndex) {
                item.style.backgroundColor = 'rgba(255, 165, 0, 0.15)';
                item.style.fontWeight = '600';
            } else {
                item.style.backgroundColor = '';
                item.style.fontWeight = '';
            }
        });
    }
    const NEWS_LOOKBACK_MS = 3 * 24 * 60 * 60 * 1000;
    const PROGRESS_FETCH_THRESHOLD = 30;
    const PROGRESS_ANALYZE_THRESHOLD = 60;
    const DEBUG_LOGS = new URLSearchParams(window.location.search).has('debug');
    let autocompleteController = null;

    function debugLog(...args) {
        if (DEBUG_LOGS) {
            console.log(...args);
        }
    }

    const utils = window.StockScreenUtils || {};
    const escapeHtml = utils.escapeHtml || (value => String(value ?? ''));
    const sanitizeSymbol = utils.sanitizeSymbol || (value => String(value ?? '').replace(/[^A-Za-z0-9.^-]/g, ''));
    const sanitizeUrl = utils.sanitizeUrl || (() => '');
    const fetchJson = utils.fetchJson;
    const showError = message => utils.showError(errorMessage, message, {
        hiddenClass: 'd-none',
        textTarget: document.getElementById('errorText'),
    });

    function getSentimentClass(sentiment) {
        const normalized = String(sentiment || '').toLowerCase();
        if (['very positive', 'positive', 'bullish'].includes(normalized)) return 'positive';
        if (['very negative', 'negative', 'bearish'].includes(normalized)) return 'negative';
        if (normalized === 'neutral') return 'neutral';
        return 'unknown';
    }

    function positionFloatingDropdown(dropdown) {
        if (!dropdown || !searchInput) return;
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
        setTimeout(() => {
            if (sampleStocksDropdown) {
                sampleStocksDropdown.classList.add('show');
            }
        }, 10);
    }

    function hideSampleStocksDropdown() {
        if (!sampleStocksDropdown) return;
        sampleStocksDropdown.classList.remove('show');
        setTimeout(() => {
            if (sampleStocksDropdown) {
                sampleStocksDropdown.style.display = 'none';
            }
        }, 300);
    }
    
    // Load default market data on page load (US markets by default)
    loadDefaultMarkets('US');
    toggleStockSections('US'); // Set initial stock sections
    
    // Make title clickable to reset search and go to home
    const mainTitle = document.getElementById('mainTitle');

    if (mainTitle) {
        mainTitle.addEventListener('click', function(e) {
            e.preventDefault();

            // Reset search input
            if (searchInput) {
                searchInput.value = '';
            }

            // Hide all results and dropdowns
            if (resultsSection) {
                resultsSection.classList.add('d-none');
            }
            dismissAutocomplete();
            if (sampleStocksDropdown) {
                sampleStocksDropdown.classList.remove('show');
                sampleStocksDropdown.style.display = 'none';
            }
            
            // Clear any error messages
            if (errorMessage) {
                errorMessage.classList.add('d-none');
            }

            switchTab('main');
            if (window.location.hash) {
                window.history.replaceState(null, '', window.location.pathname);
            }
            
            // Scroll to top
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    } else {
        console.error('Main title element not found!');
    }
    
    // Market selector dropdown
    const marketSelect = document.getElementById('marketSelect');
    if (marketSelect) {
        marketSelect.addEventListener('change', function() {
            loadDefaultMarkets(this.value);
            toggleStockSections(this.value);
        });
    }
    
    // Function to toggle stock sections based on country
    function toggleStockSections(country) {
        const usStocksSection = document.getElementById('usStocksSection');
        const indianStocksSection = document.getElementById('indianStocksSection');
        
        if (country === 'US') {
            if (usStocksSection) usStocksSection.style.display = 'block';
            if (indianStocksSection) indianStocksSection.style.display = 'none';
        } else if (country === 'IN') {
            if (usStocksSection) usStocksSection.style.display = 'none';
            if (indianStocksSection) indianStocksSection.style.display = 'block';
        }
    }
    
    // Load stock dropdown from API
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
    loadStockDropdown();

    window.addEventListener('resize', function() {
        if (sampleStocksDropdown && sampleStocksDropdown.style.display === 'block') {
            positionFloatingDropdown(sampleStocksDropdown);
        }
        if (autocompleteDropdown && autocompleteDropdown.style.display === 'block') {
            positionFloatingDropdown(autocompleteDropdown);
        }
    });

    window.addEventListener('scroll', function() {
        if (sampleStocksDropdown && sampleStocksDropdown.style.display === 'block') {
            positionFloatingDropdown(sampleStocksDropdown);
        }
        if (autocompleteDropdown && autocompleteDropdown.style.display === 'block') {
            positionFloatingDropdown(autocompleteDropdown);
        }
    }, true);

    
    // Show sample stocks when clicking on search input and clear existing results
    searchInput.addEventListener('focus', function() {
        // Clear existing results when focusing on search input
        autoReset();
        
        if (this.value.trim() === '' && sampleStocksDropdown) {
            showSampleStocksDropdown();
        }
    });
    
    // Clear search input when clicking on it (if it has a value)
    searchInput.addEventListener('click', function() {
        if (this.value.trim() !== '') {
            this.value = '';
            autoReset();
            if (sampleStocksDropdown) {
                showSampleStocksDropdown();
            }
        }
    });
    
    // Hide sample stocks when clicking outside
    document.addEventListener('click', function(e) {
        if (sampleStocksDropdown && !searchInput.contains(e.target) && !sampleStocksDropdown.contains(e.target)) {
            hideSampleStocksDropdown();
        }
    });
    
    // Handle sample stock selection
    sampleStocksDropdown.addEventListener('click', function(e) {
        e.preventDefault();
        if (e.target.classList.contains('dropdown-item')) {
            const symbol = e.target.dataset.symbol;
            searchInput.value = symbol;
            hideSampleStocksDropdown();
            analyzeSentiment(symbol);
        }
    });
    
    // Search input with autocomplete (faster)
    searchInput.addEventListener('input', function() {
        const query = this.value.trim();
        
        clearTimeout(searchTimeout);
        
        // Only auto-reset if there are existing results and user is typing a new query
        if (query.length > 0 && !resultsSection.classList.contains('d-none')) {
            autoReset();
        }
        
        // Hide sample stocks when typing
        hideSampleStocksDropdown();
        
        if (query.length < 1) {
            dismissAutocomplete();
            return;
        }
        
        searchTimeout = setTimeout(() => {
            if (autocompleteController) {
                autocompleteController.abort();
            }
            autocompleteController = new AbortController();
            fetchJson(`/api/search_stocks?q=${encodeURIComponent(query)}`, { signal: autocompleteController.signal })
                .then(data => {
                    displayAutocomplete(data);
                })
                .catch(error => {
                    if (error.name === 'AbortError') return;
                    console.error('Error fetching autocomplete:', error);
                });
        }, AUTOCOMPLETE_DEBOUNCE_MS); // Faster response time
    });
    
    function displayAutocomplete(results) {
        if (results.length === 0) {
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

        // Add click handlers
        autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', function() {
                const symbol = this.dataset.symbol;
                searchInput.value = symbol;
                dismissAutocomplete();
                analyzeSentiment(symbol); // Show news immediately on click
            });
        });
    }

    function renderNewsToContainer(newsItems, container) {
        if (!container) return;

        // Drop any article whose sentiment resolves to N/A.
        const allItems = (Array.isArray(newsItems) ? newsItems : [])
            .filter(item => getDisplaySentiment(item?.sentiment || 'Unknown') !== 'N/A');
        const cutoff = Date.now() - NEWS_LOOKBACK_MS;
        let recentNewsItems = allItems.filter(item => {
            const published = Number(item?.published || 0);
            const publishedMs = published < 1e12 ? published * 1000 : published;
            return publishedMs >= cutoff;
        });

        // If the 3-day window filters everything out, show the most recent
        // items anyway - an empty panel reads as "news is broken".
        if (recentNewsItems.length === 0 && allItems.length > 0) {
            recentNewsItems = allItems
                .slice()
                .sort((a, b) => Number(b?.published || 0) - Number(a?.published || 0))
                .slice(0, 10);
        }

        if (recentNewsItems.length === 0) {
            container.innerHTML = '<div class="col-12"><p class="text-muted text-center">No news items found for this symbol.</p></div>';
            return;
        }

        container.innerHTML = recentNewsItems.map(item => {
            const titleRaw = String(item?.title || '');
            const summaryRaw = String(item?.summary || '');
            const summaryTrimmed = summaryRaw.length > 200 ? `${summaryRaw.slice(0, 200)}...` : summaryRaw;
            const publisher = escapeHtml(item?.publisher || 'Unknown source');
            const published = Number(item?.published || 0);
            const publishedMs = published < 1e12 ? published * 1000 : published;
            const timeLabel = publishedMs ? new Date(publishedMs).toLocaleString('en-US', {
                month: 'short',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
            }) : '--:--';
            const sentimentLabel = escapeHtml(getDisplaySentiment(item?.sentiment || 'Unknown'));
            const sentimentClass = getSentimentBadgeColor(item?.sentiment || 'Unknown');
            const showSentimentBadge = !(container.id === 'marketHeadlines' && sentimentLabel === 'N/A');
            const safeLink = sanitizeUrl(item?.link);
            const safeAriaTitle = escapeHtml(`Read full article: ${titleRaw.slice(0, 50)}...`);

            return `
                <div class="news-item ${getSentimentClass(item?.sentiment)}">
                    <div class="d-flex align-items-start gap-2">
                        <span style="font-family: var(--font-mono); font-size: 0.7rem; color: #00D4FF; white-space: nowrap; min-width: 90px; padding-top: 2px;">${escapeHtml(timeLabel)}</span>
                        <div class="flex-grow-1">
                            <div class="news-header-mobile mb-1">
                                ${safeLink ? `<a href="${safeLink}" target="_blank" rel="noopener noreferrer" aria-label="${safeAriaTitle}">${escapeHtml(titleRaw)}</a>` : escapeHtml(titleRaw)}
                            </div>
                            <p class="news-snippet mb-1">${escapeHtml(summaryTrimmed)}</p>
                            <div class="d-flex align-items-center gap-2">
                                <span class="publisher">${publisher}</span>
                                ${showSentimentBadge ? `<span class="badge ${sentimentClass} sentiment-pill sentiment-badge">${sentimentLabel}</span>` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderNewsItems(newsItems) {
        const newsItemsContainer = document.getElementById('newsItems');
        renderNewsToContainer(newsItems, newsItemsContainer);
    }
    
    // Hide autocomplete when clicking outside
    document.addEventListener('click', function(e) {
        if (autocompleteDropdown && !searchInput.contains(e.target) && !autocompleteDropdown.contains(e.target)) {
            dismissAutocomplete();
        }
    });
    
    // Form submission (prevent default form behavior)
    sentimentForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const symbol = sanitizeSymbol(searchInput.value).toUpperCase();
        if (!symbol) return;
        analyzeSentiment(symbol);
    });
    
    // Global error handler for async listener errors (browser extensions)
    window.addEventListener('unhandledrejection', function(event) {
        if (event.reason && event.reason.message && 
            event.reason.message.includes('listener indicated an asynchronous response')) {
            console.warn('Browser extension async error (non-critical):', event.reason.message);
            event.preventDefault(); // Prevent the error from showing in console
        }
    });

     // Theme functionality is now handled in main.js

    // Tab switching via nav links
    const mainTabContent = document.getElementById('mainTabContent');
    const newsTabContent = document.getElementById('newsTabContent');
    const navTabLinks = document.querySelectorAll('.nav-link-item[data-tab]');

    function switchTab(tab) {
        // Update nav link active states
        navTabLinks.forEach(link => {
            if (link.dataset.tab === tab) {
                link.classList.add('nav-tab-active');
            } else {
                link.classList.remove('nav-tab-active');
            }
        });

        if (tab === 'main') {
            if (mainTabContent) mainTabContent.style.display = '';
            if (newsTabContent) newsTabContent.style.display = 'none';
            if (window.location.hash === '#news') {
                window.history.replaceState(null, '', window.location.pathname);
            }
        } else if (tab === 'news') {
            if (mainTabContent) mainTabContent.style.display = 'none';
            if (newsTabContent) newsTabContent.style.display = '';
            if (window.location.hash !== '#news') {
                window.history.replaceState(null, '', '#news');
            }
        }
    }

    navTabLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            switchTab(this.dataset.tab);
        });
    });

    // Check URL hash for direct tab navigation
    if (window.location.hash === '#news') {
        switchTab('news');
    } else {
        // Mark Markets as active by default
        switchTab('main');
    }

    if (backToMarketsBtn) {
        backToMarketsBtn.addEventListener('click', function() {
            switchTab('main');
        });
    }

    // News feed functionality
    // Quick-pick stock suggestions
    document.querySelectorAll('.quick-pick').forEach(pick => {
        pick.addEventListener('click', function() {
            const symbol = this.dataset.symbol;
            if (symbol && searchInput) {
                searchInput.value = symbol;
                analyzeSentiment(symbol);
            }
        });
    });

    // ─── Market Headlines (Currents API — cached server-side in Supabase) ───

    function updateHeadlinesTimestamp(fetchedAt) {
        const label = document.getElementById('headlinesLastUpdated');
        if (!label) return;
        if (!fetchedAt) { label.textContent = ''; return; }
        const ts = new Date(fetchedAt).getTime();
        const diff = Date.now() - ts;
        const mins = Math.floor(diff / 60000);
        if (mins < 1) label.textContent = 'Updated just now';
        else if (mins < 60) label.textContent = `Updated ${mins}m ago`;
        else label.textContent = `Updated ${Math.floor(mins / 60)}h ${mins % 60}m ago`;
    }

    function loadMarketHeadlines() {
        const headlinesContainer = document.getElementById('marketHeadlines');
        if (!headlinesContainer) return;

        headlinesContainer.innerHTML = '<div class="text-center py-3"><span class="terminal-cursor">LOADING HEADLINES</span></div>';

        fetchJson('/api/currents_news')
            .then(data => {
                if (data.news && data.news.length > 0) {
                    const src = data.cached ? 'Supabase cache' : 'Currents API';
                    debugLog(`[Headlines] Loaded ${data.news.length} items from ${src}`);
                    renderCurrentsNews(data.news, headlinesContainer);
                    updateHeadlinesTimestamp(data.fetched_at || null);
                } else {
                    debugLog('[Headlines] No Currents results, falling back to SPY news');
                    loadFallbackHeadlines(headlinesContainer);
                }
            })
            .catch(err => {
                console.error('[Headlines] Fetch error:', err);
                loadFallbackHeadlines(headlinesContainer);
            });
    }

    function loadFallbackHeadlines(container) {
        fetchJson('/api/news?symbol=SPY')
            .then(data => {
                if (data.news_items && data.news_items.length > 0) {
                    renderNewsToContainer(data.news_items, container);
                } else {
                    container.innerHTML = '<div class="text-center py-3" style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">No headlines available</div>';
                }
            })
            .catch(() => {
                container.innerHTML = '<div class="text-center py-3" style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">Unable to load headlines</div>';
            });
    }

    function renderCurrentsNews(items, container) {
        if (!container || !items || items.length === 0) {
            container.innerHTML = '<div class="text-center py-3" style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">No headlines available</div>';
            return;
        }

        container.innerHTML = items.map(item => {
            const titleRaw = String(item.title || '');
            const summaryRaw = String(item.summary || '');
            const summaryTrimmed = summaryRaw.length > 200 ? `${summaryRaw.slice(0, 200)}...` : summaryRaw;
            const publisher = escapeHtml(item.publisher || 'News');
            const published = Number(item.published || 0);
            const publishedMs = published < 1e12 ? published * 1000 : published;
            const timeLabel = publishedMs ? new Date(publishedMs).toLocaleString('en-US', {
                month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
            }) : '--:--';
            const safeLink = sanitizeUrl(item.link);

            return `
                <div class="news-item">
                    <div class="d-flex align-items-start gap-2">
                        <span style="font-family: var(--font-mono); font-size: 0.7rem; color: #00D4FF; white-space: nowrap; min-width: 90px; padding-top: 2px;">${escapeHtml(timeLabel)}</span>
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

    // Load headlines on page load
    loadMarketHeadlines();

    // Chart range toggle
    const chartRangeToggle = document.getElementById('chartRangeToggle');
    if (chartRangeToggle) {
        chartRangeToggle.addEventListener('click', function(e) {
            const btn = e.target.closest('.chart-range-btn');
            if (!btn || !currentSymbol) return;

            const period = btn.dataset.period;

            // Update active button
            chartRangeToggle.querySelectorAll('.chart-range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Fetch new chart data
            fetchJson(`/api/chart_data?symbol=${encodeURIComponent(currentSymbol)}&period=${period}`)
                .then(data => {
                    currentAnalysisData = {
                        ...(currentAnalysisData || {}),
                        ...data,
                        sentiment_timeline: currentAnalysisData?.sentiment_timeline || [],
                        sentiment_data: currentAnalysisData?.sentiment_data || [],
                        sentiment_divergence: currentAnalysisData?.sentiment_divergence || 0,
                    };
                    // Rebuild chart with new data
                    createPriceSentimentChart(currentAnalysisData);
                    renderTraderMetrics(currentAnalysisData);
                    // Update price display
                    updateStockPrice(data);
                })
                .catch(err => console.error('Chart range fetch error:', err));
        });
    }

    document.querySelectorAll('.indicator-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            if (currentAnalysisData) {
                createPriceSentimentChart(currentAnalysisData);
            }
        });
    });

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
                        <span class="terminal-cursor" style="color: #FF3B3B;">ERROR: MARKET DATA UNAVAILABLE</span>
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
    
    // Auto-reset function (called when starting new search)
    function autoReset() {
        // Hide all sections
        resultsSection.classList.add('d-none');
        progressSection.style.display = 'none';
        progressSection.classList.add('d-none');
        errorMessage.classList.add('d-none');

        // Show quick suggestions again
        const quickSuggestions = document.getElementById('quickSuggestions');
        if (quickSuggestions) {
            quickSuggestions.style.display = '';
        }
        
        
        // Button removed - no need to reset button state
        
        // Reset progress bar
        const progressBar = document.getElementById('progressBar');
        if (progressBar) {
            progressBar.style.width = '0%';
        }
        
         // Clear news items
         const newsItemsContainer = document.getElementById('newsItems');
         if (newsItemsContainer) {
             newsItemsContainer.innerHTML = '';
         }
         
         // Clear insights
         const insightsContent = document.getElementById('insightsContent');
         if (insightsContent) {
             insightsContent.innerHTML = '';
         }
        
        
        // Clear stock price display only if no results are showing
        if (resultsSection.classList.contains('d-none')) {
            const stockPrice = document.getElementById('stockPrice');
            const priceChange = document.getElementById('priceChange');
            if (stockPrice) {
                stockPrice.textContent = '$0.00';
            }
            if (priceChange) {
                priceChange.textContent = '+$0.00 (0.00%)';
                priceChange.className = 'text-muted';
            }
        }
        
        // Destroy chart if it exists
        if (window.priceSentimentChartInstance) {
            window.priceSentimentChartInstance.destroy();
            window.priceSentimentChartInstance = null;
        }
    }
    
    // Reset all function (kept for compatibility)
    window.resetAll = function() {
        // Clear search input
        searchInput.value = '';
        
        // Hide dropdowns
        dismissAutocomplete();
        sampleStocksDropdown.style.display = 'none';
        
        // Call auto-reset
        autoReset();
        
        // Default markets section stays visible
    };
    
    // ─── Finnhub — Stock-specific news (cached server-side in Supabase) ───

    function fetchFinnhubNews(symbol) {
        return fetchJson(`/api/finnhub_news?symbol=${encodeURIComponent(symbol)}`)
            .then(data => {
                const src = data.cached ? 'Supabase cache' : 'Finnhub API';
                debugLog(`[Finnhub] ${symbol}: ${(data.news || []).length} items from ${src}`);
                return data.news || [];
            })
            .catch(err => {
                console.error(`[Finnhub] Error fetching ${symbol}:`, err);
                return [];
            });
    }

    function analyzeSentiment(symbol) {
        const cleanSymbol = sanitizeSymbol(symbol).toUpperCase();
        if (!cleanSymbol) {
            showError('Please enter a stock symbol.');
            return;
        }

        if (searchInput) {
            searchInput.value = cleanSymbol;
        }

        switchTab('news');

        // Show progress bar
        progressSection.style.display = 'block';
        progressSection.classList.remove('d-none');
        resultsSection.classList.add('d-none');
        errorMessage.classList.add('d-none');

        // Simulate progress
        let progress = 0;
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');

        const progressInterval = setInterval(() => {
            progress += Math.random() * 15;
            if (progress > 90) progress = 90;
            if (progressBar) {
                progressBar.style.width = progress + '%';
            }

            if (progressText) {
                if (progress < PROGRESS_FETCH_THRESHOLD) {
                    progressText.textContent = 'Fetching news articles...';
                } else if (progress < PROGRESS_ANALYZE_THRESHOLD) {
                    progressText.textContent = 'Analyzing sentiment...';
                } else {
                    progressText.textContent = 'Processing results...';
                }
            }
        }, 200);

        // Parallel fetch: server-cached Finnhub news + yfinance sentiment analysis
        const finnhubPromise = fetchFinnhubNews(cleanSymbol);
        const sentimentPromise = fetchJson('/api/analyze_sentiment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: cleanSymbol }),
        });

        Promise.all([sentimentPromise, finnhubPromise])
        .then(([data, finnhubNews]) => {
            // Merge Finnhub news into the results (deduplicate by title)
            if (finnhubNews.length > 0 && data.news_items) {
                const existingTitles = new Set(data.news_items.map(n => (n.title || '').toLowerCase().trim()));
                const newItems = finnhubNews
                    .filter(fn => !existingTitles.has((fn.title || '').toLowerCase().trim()))
                    .map(fn => ({
                        title: fn.title,
                        summary: fn.summary || '',
                        link: fn.link,
                        publisher: fn.publisher || 'Finnhub',
                        published: fn.published,
                        sentiment: 'Unknown', // Finnhub items don't have sentiment analysis
                    }));
                data.news_items = [...data.news_items, ...newItems]
                    .sort((a, b) => (b.published || 0) - (a.published || 0));
                debugLog(`[Finnhub] Merged ${newItems.length} additional news items`);
            }

            // Update stock price display
            updateStockPrice(data);

            // Complete progress
            clearInterval(progressInterval);
            if (progressBar) {
                progressBar.style.width = '100%';
            }
            if (progressText) {
                progressText.textContent = 'Analysis complete!';
            }

            setTimeout(() => {
                progressSection.style.display = 'none';
                progressSection.classList.add('d-none');

                if (data.error) {
                    showError(data.error);
                    return;
                }

                displayResults(data);
            }, 500);
        })
        .catch(error => {
            clearInterval(progressInterval);

            progressSection.style.display = 'none';
            progressSection.classList.add('d-none');

            if (error.message && error.message.includes('listener indicated an asynchronous response')) {
                console.warn('Browser extension async error (non-critical):', error.message);
                return;
            }

            showError('An error occurred while analyzing sentiment. Please try again.');
            console.error('Error:', error);
        });
    }
    
    // Store the current symbol for chart range switching
    let currentSymbol = '';
    let currentCurrency = '$';
    let currentAnalysisData = null;
    let currentIndicatorsData = null;
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
                `RSI 14: <span style="color: var(--text-primary);">${Number(latest.rsi_14 || 0).toFixed(1)}</span>`,
                `MACD: <span style="color: var(--text-primary);">${Number(latest.macd || 0).toFixed(2)}</span>`,
                `ATR 14: <span style="color: var(--text-primary);">${Number(latest.atr_14 || 0).toFixed(2)}</span>`,
                `Volume ratio: <span style="color: var(--text-primary);">${Number(latest.volume_ratio || 0).toFixed(2)}x</span>`,
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

    function renderTraderMetrics(data, indicatorPayload = currentIndicatorsData) {
        const panel = document.getElementById('traderMetricsPanel');
        const togglePanel = document.getElementById('technicalTogglePanel');
        if (panel) panel.style.display = '';
        if (togglePanel) togglePanel.style.display = '';
        renderVolumeLiquidity(data);
        renderSentimentTimeline(data);
        renderIndicatorPanel(indicatorPayload);
    }

    function fetchIndicators(symbol) {
        return fetchJson(`/api/indicators/${encodeURIComponent(symbol)}`)
            .then(payload => {
                currentIndicatorsData = payload;
                renderTraderMetrics(currentAnalysisData || {}, payload);
                createPriceSentimentChart(currentAnalysisData || {});
                return payload;
            })
            .catch(error => {
                console.error('Indicator fetch error:', error);
                currentIndicatorsData = { indicators: [], latest: {} };
                renderIndicatorPanel(currentIndicatorsData);
                return currentIndicatorsData;
            });
    }

    function displayResults(data) {
        // Track current symbol for range toggle
        currentSymbol = data.symbol || '';
        currentCurrency = data.currency || '$';
        currentAnalysisData = data;
        currentIndicatorsData = null;

        if (stockPageTitle) {
            const titleSymbol = String(data.symbol || '');
            const titleCompany = String(data.company_name || '');
            stockPageTitle.textContent = titleCompany ? `${titleCompany} (${titleSymbol})` : `${titleSymbol} ANALYSIS`;
        }

        // Reset chart range toggle to 30D
        if (chartRangeToggle) {
            chartRangeToggle.querySelectorAll('.chart-range-btn').forEach(b => b.classList.remove('active'));
            const defaultBtn = chartRangeToggle.querySelector('[data-period="30d"]');
            if (defaultBtn) defaultBtn.classList.add('active');
        }

        // Update stock price display
        updateStockPrice(data);

        // Hide quick suggestions when results show
        const quickSuggestions = document.getElementById('quickSuggestions');
        if (quickSuggestions) {
            quickSuggestions.style.display = 'none';
        }

        // Show stock chart card
        const sentimentCard = document.querySelector('.equal-height > [class*="col-lg"]');
        if (sentimentCard) {
            sentimentCard.style.display = 'block';
        }
        
         // Create price-sentiment chart
         createPriceSentimentChart(data);
         renderTraderMetrics(data, { indicators: [], latest: {} });
         if (currentSymbol) {
             fetchIndicators(currentSymbol);
         }
         
         // Display insights
         if (data.insights) {
             window._lastInsights = data.insights;
             window._lastKeywords = data.keywords || [];
             displayInsights(data.insights);
         }

         // Display news items with sentiment (filtered to last 3 days)
         renderNewsItems(data.news_items);
        
         // Show results section
         resultsSection.classList.remove('d-none');
         
         // Don't clear search input - keep the stock name visible
         dismissAutocomplete();
     }
     
     // Display insights function
     function displayInsights(insights) {
         const insightsContent = document.getElementById('insightsContent');
         if (!insightsContent || !insights) return;

         if (insights.verdict) {
             displayRichInsights(insightsContent, insights);
         } else {
             displayLegacyInsights(insightsContent, insights);
         }
     }

     function displayLegacyInsights(el, insights) {
         const marketOutlook = escapeHtml(insights.market_outlook || '');
         const opportunities = (insights.opportunities || []).map(opp => `<li class="mb-2">${escapeHtml(opp)}</li>`).join('');
         const keyPoints = (insights.key_points || []).map(point => `<li class="mb-2">${escapeHtml(point)}</li>`).join('');
         const riskFactors = (insights.risk_factors || []).map(risk => `<li class="mb-2">${escapeHtml(risk)}</li>`).join('');

         el.innerHTML = `
             <div class="row">
                 <div class="col-md-6 mb-4">
                     <h6 class="text-primary mb-3">Market Outlook</h6>
                     <p class="mb-3">${marketOutlook}</p>
                     <h6 class="text-success mb-3">Opportunities</h6>
                      <ul class="list-unstyled">
                         ${opportunities}
                     </ul>
                 </div>
                 <div class="col-md-6 mb-4">
                     <h6 class="text-warning mb-3">Key Points</h6>
                     <ul class="list-unstyled">
                         ${keyPoints}
                     </ul>
                     <h6 class="text-danger mb-3">Risk Factors</h6>
                     <ul class="list-unstyled">
                         ${riskFactors}
                     </ul>
                 </div>
             </div>`;
     }

     function displayRichInsights(el, ins) {
         const v = ins.verdict || {};
         const signalColor = v.signal === 'Bullish' ? 'var(--positive)' : v.signal === 'Bearish' ? 'var(--negative)' : 'var(--neutral-warn)';
         const signalBadge = v.signal === 'Bullish' ? 'bg-success' : v.signal === 'Bearish' ? 'bg-danger' : 'bg-warning text-dark';
         const confBadge = v.confidence_label === 'High' ? 'bg-success' : v.confidence_label === 'Medium' ? 'bg-warning text-dark' : 'bg-danger';

         function sevBadge(s) {
             const cls = s === 'High' ? 'bg-danger' : s === 'Medium' ? 'bg-warning text-dark' : 'bg-secondary';
             return `<span class="badge ${cls} severity-badge">${escapeHtml(s)}</span>`;
         }

         // Build catalysts
         const catalystsHtml = (ins.catalysts || []).map(c => `
             <div class="catalyst-item mb-2">
                 <span class="badge bg-secondary me-2">${escapeHtml(c.tag || '')}</span>
                 <span>${escapeHtml(c.text || '')}</span>
             </div>
         `).join('') || '<p class="text-muted mb-0">No catalysts identified.</p>';

         // Build risks
         const risksHtml = (ins.risks || []).map(r => `
             <div class="risk-item mb-2">
                 
                 ${sevBadge(r.severity || 'Low')}
                 <span class="ms-2">${escapeHtml(r.text || '')}</span>
             </div>
         `).join('') || '<p class="text-muted mb-0">No specific risks identified.</p>';

         // Source breakdown bar
         const sb = ins.source_breakdown || {};
         const bullPct = Math.max(0, Math.min(100, Number(sb.bullish_pct) || 0));
         const neuPct = Math.max(0, Math.min(100, Number(sb.neutral_pct) || 0));
         const bearPct = Math.max(0, Math.min(100, Number(sb.bearish_pct) || 0));

         // Velocity
         const vel = ins.sentiment_velocity || {};
         const trend = ins.trending || {};
         const keywords = (ins.keywords_enriched || window._lastKeywords || []).slice(0, 12);
         const keywordHtml = keywords.map(kw => {
             const sentimentName = String(kw.sentiment || 'neutral').toLowerCase();
             const color = sentimentName === 'positive'
                 ? 'var(--positive)'
                 : sentimentName === 'negative'
                     ? 'var(--negative)'
                     : 'var(--text-muted)';
             return `<span class="badge bg-secondary me-1 mb-1" style="color:${color};">${escapeHtml(kw.text || kw.word || '')}</span>`;
         }).join('') || '<span class="text-muted">No keyword cluster available.</span>';

         // Report copy
         const report = ins.report_summary || {};

         el.innerHTML = `
             <!-- Verdict -->
             <div class="verdict-card p-3 mb-3" style="border-left: 4px solid ${signalColor}">
                 <div class="d-flex align-items-center justify-content-between mb-2">
                     <div class="d-flex align-items-center" style="min-height: 32px;">
                         <span class="badge ${signalBadge} verdict-badge me-3">${escapeHtml(v.signal || 'Neutral')}</span>
                         <span class="badge ${confBadge} verdict-badge">${escapeHtml(v.confidence_label || 'Low')} confidence</span>
                     </div>
                     <button class="btn btn-sm btn-outline-secondary copy-report-btn" title="Copy report to clipboard">
                         Copy
                     </button>
                 </div>
                 <p class="mb-1 fw-bold" style="font-size: 1.1em;">${escapeHtml(v.one_liner || '')}</p>
                 ${v.confidence_explanation ? `<p class="text-muted mb-2" style="font-size: 0.85em;">${escapeHtml(v.confidence_explanation)}</p>` : ''}
                 ${ins.analyst_note ? `<p class="mb-0" style="font-size: 0.9em;">${escapeHtml(ins.analyst_note)}</p>` : ''}
             </div>

             <!-- Velocity + Topics -->
             <div class="row mb-3">
                 <div class="col-md-4 mb-3 mb-md-0">
                     <h6 class="mb-2">SENTIMENT VELOCITY</h6>
                     <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-secondary);">
                         <span style="color: var(--accent-amber);">${escapeHtml(vel.trend || 'stable')}</span>
                         ${vel.label ? ` - ${escapeHtml(vel.label)}` : ''}
                     </div>
                 </div>
                 <div class="col-md-4 mb-3 mb-md-0">
                     <h6 class="mb-2">TRENDING WATCH</h6>
                     <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-secondary);">
                         <span style="color: var(--accent-cyan);">${escapeHtml(trend.category || 'other')}</span>
                         ${trend.what_to_watch ? ` - ${escapeHtml(trend.what_to_watch)}` : ''}
                     </div>
                 </div>
                 <div class="col-md-4">
                     <h6 class="mb-2">KEYWORDS</h6>
                     <div>${keywordHtml}</div>
                 </div>
             </div>

             <!-- Catalysts + Risks -->
             <div class="row mb-3">
                 <div class="col-md-6 mb-3 mb-md-0">
                     <h6 class="text-success mb-3">POSITIVES</h6>
                     ${catalystsHtml}
                 </div>
                 <div class="col-md-6">
                     <h6 class="text-danger mb-3">RISKS</h6>
                     ${risksHtml}
                 </div>
             </div>

             <!-- Source Breakdown -->
             <div class="row mb-3">
                 <div class="col-md-12">
                     <h6 class="mb-2">SOURCE BREAKDOWN</h6>
                     <div class="source-bar mb-2">
                         ${bullPct > 0 ? `<div class="source-bar-bull" style="width:${bullPct}%" title="Bullish ${bullPct}%"></div>` : ''}
                         ${neuPct > 0 ? `<div class="source-bar-neu" style="width:${neuPct}%" title="Neutral ${neuPct}%"></div>` : ''}
                         ${bearPct > 0 ? `<div class="source-bar-bear" style="width:${bearPct}%" title="Bearish ${bearPct}%"></div>` : ''}
                     </div>
                     <div class="d-flex justify-content-between" style="font-size:0.8em;">
                         <span class="text-success">${bullPct}% Bullish</span>
                         <span class="text-muted">${neuPct}% Neutral</span>
                         <span class="text-danger">${bearPct}% Bearish</span>
                     </div>
                     ${sb.analyst_takeaway ? `<p class="text-muted mt-1 mb-0" style="font-size:0.85em;">${escapeHtml(sb.analyst_takeaway)}</p>` : ''}
                 </div>
             </div>
         `;

         const copyBtn = el.querySelector('.copy-report-btn');
         if (copyBtn) {
             copyBtn.addEventListener('click', function() {
                 copyReport(this);
             });
         }
     }

     function copyReport(btn) {
         const ins = window._lastInsights;
         if (!ins) return;
         const v = ins.verdict || {};
         const report = ins.report_summary || {};
         const catalysts = (ins.catalysts || []).map(c => `  - [${c.direction}] ${c.tag}: ${c.text}`).join('\n');
         const risks = (ins.risks || []).map(r => `  - [${r.severity}] ${r.text}`).join('\n');
         const text = [
             report.title || '',
             '',
             `Signal: ${v.signal} (${v.confidence_label} confidence)`,
             v.one_liner || '',
             '',
             report.executive_summary || '',
             '',
             catalysts ? `Catalysts:\n${catalysts}` : '',
             risks ? `Risks:\n${risks}` : '',
             '',
             report.disclaimer || '',
         ].filter(Boolean).join('\n');

         navigator.clipboard.writeText(text).then(() => {
             const orig = btn.innerHTML;
             btn.innerHTML = 'Copied';
             setTimeout(() => { btn.innerHTML = orig; }, 2000);
         });
     }
    
     function getSentimentBadgeColor(sentiment) {
         const normalized = String(sentiment || '').toLowerCase();
         switch(normalized) {
             case 'very positive': 
             case 'positive': 
             case 'bullish': return 'bg-success';
             case 'negative': 
             case 'very negative': 
             case 'bearish': return 'bg-danger';
             case 'neutral': return 'bg-warning text-dark';
             default: return 'bg-secondary';
         }
     }
     
     function getDisplaySentiment(sentiment) {
         const normalized = String(sentiment || '').toLowerCase();
         switch(normalized) {
             case 'very positive': 
             case 'positive': return 'Bullish';
             case 'negative': 
             case 'very negative': return 'Bearish';
             case 'neutral': return 'Neutral';
             case 'unknown': return 'N/A';
             default: return sentiment;
         }
     }
    
    // Update stock price display
    function updateStockPrice(data) {
        const stockPriceElement = document.getElementById('stockPrice');
        const priceChangeElement = document.getElementById('priceChange');

        if (stockPriceElement && data.current_price) {
            const currency = data.currency || '$';
            const price = parseFloat(data.current_price).toFixed(2);
            stockPriceElement.textContent = `${currency}${price}`;
        }

        if (priceChangeElement && data.price_change !== undefined && data.price_change_percent !== undefined) {
            const isPositive = data.price_change >= 0;
            const sign = isPositive ? '+' : '';
            const currency = data.currency || '$';
            const priceChange = parseFloat(data.price_change).toFixed(2);
            const priceChangePercent = parseFloat(data.price_change_percent).toFixed(2);
            priceChangeElement.textContent = `${sign}${currency}${priceChange} (${sign}${priceChangePercent}%)`;
            priceChangeElement.className = `text-muted ${isPositive ? 'price-positive' : 'price-negative'}`;
        }
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

        const indicatorRows = currentIndicatorsData?.indicators || [];
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

    // ─── Terminal extras: world clocks, ticker tape, market movers ───

    const TAPE_SYMBOLS = ['^GSPC', '^DJI', 'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'JPM', 'NFLX', 'V'];
    const QUOTES_REFRESH_MS = 60 * 1000;

    function initTerminalClocks() {
        const zones = [
            { id: 'clockNY', tz: 'America/New_York' },
            { id: 'clockLDN', tz: 'Europe/London' },
            { id: 'clockMUM', tz: 'Asia/Kolkata' },
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
                    analyzeSentiment(symbol);
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
            body.innerHTML = '<tr><td colspan="9" class="text-center py-3" style="color: var(--text-muted);">NO QUOTE DATA</td></tr>';
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
                if (symbol) analyzeSentiment(symbol);
            });
        });
    }

    function loadTerminalQuotes() {
        fetchJson(`/api/quotes?symbols=${encodeURIComponent(TAPE_SYMBOLS.join(','))}`)
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
                    track.innerHTML = '<span class="ticker-loading" style="color: var(--negative);">TAPE UNAVAILABLE</span>';
                }
                const body = document.getElementById('moversTableBody');
                if (body) {
                    body.innerHTML = '<tr><td colspan="8" class="text-center py-3" style="color: var(--text-muted);">QUOTES UNAVAILABLE</td></tr>';
                }
            });
    }

    initTerminalClocks();
    loadTerminalQuotes();
    setInterval(loadTerminalQuotes, QUOTES_REFRESH_MS);

});
