// Main JavaScript for Stock Sentiment Analyzer — Dark Glass Terminal

document.addEventListener('DOMContentLoaded', function() {
    // Top nav hamburger menu
    const hamburger = document.getElementById('navHamburger');
    const navLinks = document.getElementById('navLinks');

    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function() {
            navLinks.classList.toggle('show');
            this.textContent = navLinks.classList.contains('show') ? 'CLOSE' : 'MENU';
        });

        navLinks.querySelectorAll('.nav-link-item').forEach(link => {
            link.addEventListener('click', function() {
                if (window.innerWidth <= 768) {
                    navLinks.classList.remove('show');
                    hamburger.textContent = 'MENU';
                }
            });
        });

        window.addEventListener('resize', function() {
            if (window.innerWidth > 768) {
                navLinks.classList.remove('show');
                hamburger.textContent = 'MENU';
            }
        });
    }

    // Active nav link highlighting
    // Skip tab links (data-tab) — those are managed by index-page.js
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link-item').forEach(link => {
        if (!link.dataset.tab && link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // Responsive search placeholder
    function updateSearchPlaceholder() {
        const input = document.getElementById('stockSearch');
        if (!input) return;
        if (window.innerWidth <= 480) {
            input.placeholder = 'Search stock (e.g., AAPL)';
        } else if (window.innerWidth <= 768) {
            input.placeholder = 'Enter stock symbol (e.g., AAPL, TSLA)';
        } else {
            input.placeholder = 'Enter stock symbol or company name (e.g., AAPL, TSLA, Microsoft)';
        }
    }
    updateSearchPlaceholder();
    window.addEventListener('resize', debounce(updateSearchPlaceholder, 150));

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const href = this.getAttribute('href');
            if (href && href.length > 1) {
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    });

    // Fade-in animation on scroll
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, observerOptions);

    document.querySelectorAll('.card').forEach(card => {
        card.classList.add('fade-in');
        observer.observe(card);
    });

    // Global error handler
    window.addEventListener('unhandledrejection', function(event) {
        console.error('Unhandled promise rejection:', event.reason);
    });

    // Accessibility
    function improveAccessibility() {
        const searchInput = document.getElementById('stockSearch');
        if (searchInput) {
            searchInput.setAttribute('aria-label', 'Search for stock symbol or company name');
        }
        const autocompleteDropdown = document.getElementById('autocompleteDropdown');
        if (autocompleteDropdown) {
            autocompleteDropdown.setAttribute('role', 'listbox');
            autocompleteDropdown.setAttribute('aria-label', 'Stock search suggestions');
        }
    }
    improveAccessibility();

    // Back to top
    const backToTopBtn = document.getElementById('backToTop');
    if (backToTopBtn) {
        backToTopBtn.addEventListener('click', function(e) {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });

        window.addEventListener('scroll', function() {
            backToTopBtn.classList.toggle('visible', window.pageYOffset > 300);
        });
    }

    // Market hours indicator (US and India)
    const statusDot = document.getElementById('statusDot');
    const statusLabel = document.getElementById('statusLabel');
    const marketSelect = document.getElementById('marketSelect');
    if (statusDot && statusLabel) {
        const MARKET_RULES = {
            US: {
                label: 'US',
                timeZone: 'America/New_York',
                openMinutes: 9 * 60 + 30,
                closeMinutes: 16 * 60,
            },
            IN: {
                label: 'IN',
                timeZone: 'Asia/Kolkata',
                openMinutes: 9 * 60 + 15,
                closeMinutes: 15 * 60 + 30,
            },
        };

        const marketClockFormatters = {
            US: new Intl.DateTimeFormat('en-US', {
                timeZone: MARKET_RULES.US.timeZone,
                weekday: 'short',
                hour: '2-digit',
                minute: '2-digit',
                hourCycle: 'h23',
            }),
            IN: new Intl.DateTimeFormat('en-US', {
                timeZone: MARKET_RULES.IN.timeZone,
                weekday: 'short',
                hour: '2-digit',
                minute: '2-digit',
                hourCycle: 'h23',
            }),
        };

        function getMarketClockParts(marketCode) {
            const parts = marketClockFormatters[marketCode].formatToParts(new Date());
            const extracted = {};
            parts.forEach(part => {
                extracted[part.type] = part.value;
            });
            return {
                weekday: extracted.weekday,
                hour: Number(extracted.hour || 0),
                minute: Number(extracted.minute || 0),
            };
        }

        function updateMarketStatusIndicator() {
            const selectedMarket = marketSelect && marketSelect.value === 'IN' ? 'IN' : 'US';
            const rules = MARKET_RULES[selectedMarket];
            const clock = getMarketClockParts(selectedMarket);
            const minutesNow = clock.hour * 60 + clock.minute;
            const isWeekend = clock.weekday === 'Sat' || clock.weekday === 'Sun';
            const isOpen = !isWeekend && minutesNow >= rules.openMinutes && minutesNow < rules.closeMinutes;

            statusDot.classList.toggle('closed', !isOpen);
            statusLabel.classList.toggle('open', isOpen);
            statusLabel.classList.toggle('closed', !isOpen);
            statusLabel.textContent = `${rules.label} ${isOpen ? 'OPEN' : 'CLOSED'}`;
            statusDot.title = isOpen ? `${rules.label} Market Open` : `${rules.label} Market Closed`;
        }

        updateMarketStatusIndicator();

        if (marketSelect) {
            marketSelect.addEventListener('change', updateMarketStatusIndicator);
        }
        setInterval(updateMarketStatusIndicator, 60 * 1000);
    }
});

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

