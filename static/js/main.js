// Main JavaScript for Stock Sentiment Analyzer — Dark Glass Terminal

document.addEventListener('DOMContentLoaded', function() {
    // Top nav hamburger menu
    const hamburger = document.getElementById('navHamburger');
    const navLinks = document.getElementById('navLinks');

    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function() {
            navLinks.classList.toggle('show');
            const icon = this.querySelector('i');
            icon.className = navLinks.classList.contains('show') ? 'fas fa-times' : 'fas fa-bars';
        });

        navLinks.querySelectorAll('.nav-link-item').forEach(link => {
            link.addEventListener('click', function() {
                if (window.innerWidth <= 768) {
                    navLinks.classList.remove('show');
                    hamburger.querySelector('i').className = 'fas fa-bars';
                }
            });
        });

        window.addEventListener('resize', function() {
            if (window.innerWidth > 768) {
                navLinks.classList.remove('show');
                hamburger.querySelector('i').className = 'fas fa-bars';
            }
        });
    }

    // Active nav link highlighting
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link-item').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
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

    // Keyboard navigation for autocomplete
    let currentAutocompleteIndex = -1;

    document.addEventListener('keydown', function(e) {
        const autocompleteItems = document.querySelectorAll('.autocomplete-item');
        if (autocompleteItems.length === 0) return;

        switch(e.key) {
            case 'ArrowDown':
                e.preventDefault();
                currentAutocompleteIndex = Math.min(currentAutocompleteIndex + 1, autocompleteItems.length - 1);
                updateAutocompleteSelection(autocompleteItems);
                break;
            case 'ArrowUp':
                e.preventDefault();
                currentAutocompleteIndex = Math.max(currentAutocompleteIndex - 1, -1);
                updateAutocompleteSelection(autocompleteItems);
                break;
            case 'Enter':
                e.preventDefault();
                if (currentAutocompleteIndex >= 0 && autocompleteItems[currentAutocompleteIndex]) {
                    autocompleteItems[currentAutocompleteIndex].click();
                }
                break;
            case 'Escape':
                document.getElementById('autocompleteDropdown').style.display = 'none';
                currentAutocompleteIndex = -1;
                break;
        }
    });

    function updateAutocompleteSelection(items) {
        items.forEach((item, index) => {
            if (index === currentAutocompleteIndex) {
                item.style.backgroundColor = 'rgba(59, 130, 246, 0.15)';
                item.style.fontWeight = '600';
            } else {
                item.style.backgroundColor = '';
                item.style.fontWeight = '';
            }
        });
    }

    // Copy to clipboard
    function addCopyToClipboard() {
        document.querySelectorAll('.copy-result').forEach(button => {
            button.addEventListener('click', function() {
                const textToCopy = this.dataset.copyText;
                navigator.clipboard.writeText(textToCopy).then(() => {
                    const originalText = this.innerHTML;
                    this.innerHTML = '<i class="fas fa-check me-1"></i>Copied!';
                    setTimeout(() => { this.innerHTML = originalText; }, 2000);
                }).catch(err => console.error('Failed to copy:', err));
            });
        });
    }

    // Share functionality
    function addShareFunctionality() {
        if (navigator.share) {
            document.querySelectorAll('.share-result').forEach(button => {
                button.addEventListener('click', async function() {
                    try {
                        await navigator.share({
                            title: 'Stock Sentiment Analysis',
                            text: this.dataset.shareText,
                            url: window.location.href
                        });
                    } catch (err) { console.error('Share error:', err); }
                });
            });
        }
    }

    addCopyToClipboard();
    addShareFunctionality();

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
});

// Utility functions
function formatNumber(num) {
    return new Intl.NumberFormat().format(num);
}

function formatPercentage(num) {
    return new Intl.NumberFormat('en-US', {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
    }).format(num);
}

function formatDate(timestamp) {
    return new Intl.DateTimeFormat('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    }).format(new Date(timestamp * 1000));
}

function handleError(error, userMessage = 'An unexpected error occurred') {
    console.error('Error:', error);
    const errorDiv = document.getElementById('errorMessage');
    if (errorDiv) {
        const errorText = document.getElementById('errorText');
        if (errorText) errorText.textContent = userMessage;
        errorDiv.classList.remove('d-none');
        setTimeout(() => errorDiv.classList.add('d-none'), 5000);
    }
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

