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

    // Set initial stock sections (default markets grid itself is loaded by
    // index-charts.js, which must load before this file).
    toggleStockSections('US');

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
            window.StockScreenCharts.loadDefaultMarkets(this.value);
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
                        <span class="idx-news-time">${escapeHtml(timeLabel)}</span>
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
                    container.innerHTML = '<div class="text-center py-3 idx-news-empty">No headlines available</div>';
                }
            })
            .catch(() => {
                container.innerHTML = '<div class="text-center py-3 idx-news-empty">Unable to load headlines</div>';
            });
    }

    function renderCurrentsNews(items, container) {
        if (!container || !items || items.length === 0) {
            container.innerHTML = '<div class="text-center py-3 idx-news-empty">No headlines available</div>';
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
                    window.StockScreenCharts.createPriceSentimentChart(currentAnalysisData);
                    window.StockScreenCharts.renderTraderMetrics(currentAnalysisData);
                    // Update price display
                    updateStockPrice(data);
                })
                .catch(err => console.error('Chart range fetch error:', err));
        });
    }

    document.querySelectorAll('.indicator-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            if (currentAnalysisData) {
                window.StockScreenCharts.createPriceSentimentChart(currentAnalysisData);
            }
        });
    });

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

            // Surface the server's message (e.g. rate-limit details) instead
            // of a generic one when it exists.
            showError(error.message || 'An error occurred while analyzing sentiment. Please try again.');
            console.error('Error:', error);
        });
    }

    // Store the current symbol for chart range switching
    let currentSymbol = '';
    let currentCurrency = '$';
    let currentAnalysisData = null;

    function fetchIndicators(symbol) {
        return fetchJson(`/api/indicators/${encodeURIComponent(symbol)}`)
            .then(payload => {
                window.StockScreenCharts.state.indicatorsData = payload;
                window.StockScreenCharts.renderTraderMetrics(currentAnalysisData || {}, payload);
                window.StockScreenCharts.createPriceSentimentChart(currentAnalysisData || {});
                return payload;
            })
            .catch(error => {
                console.error('Indicator fetch error:', error);
                window.StockScreenCharts.state.indicatorsData = { indicators: [], latest: {} };
                window.StockScreenCharts.renderIndicatorPanel(window.StockScreenCharts.state.indicatorsData);
                return window.StockScreenCharts.state.indicatorsData;
            });
    }

    function displayResults(data) {
        // Track current symbol for range toggle
        currentSymbol = data.symbol || '';
        currentCurrency = data.currency || '$';
        currentAnalysisData = data;
        window.StockScreenCharts.state.indicatorsData = null;

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
         window.StockScreenCharts.createPriceSentimentChart(data);
         window.StockScreenCharts.renderTraderMetrics(data, { indicators: [], latest: {} });
         if (currentSymbol) {
             fetchIndicators(currentSymbol);
         }

         // Display insights
         if (data.insights) {
             window._lastInsights = data.insights;
             window._lastKeywords = data.keywords || [];
             window.StockScreenInsights.displayInsights(data.insights);
         }

         // Display news items with sentiment (filtered to last 3 days)
         renderNewsItems(data.news_items);

         // Show results section
         resultsSection.classList.remove('d-none');

         // Don't clear search input - keep the stock name visible
         dismissAutocomplete();

         // Notify companion scripts (watchlist.js WATCH button state).
         window.dispatchEvent(new CustomEvent('analysis:shown', { detail: { symbol: currentSymbol } }));
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

    // Let companion scripts (watchlist.js) open an analysis view.
    window.StockScreenAnalyze = analyzeSentiment;

});
