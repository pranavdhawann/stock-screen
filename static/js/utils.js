(function() {
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function sanitizeSymbol(value) {
        return String(value ?? '').replace(/[^A-Za-z0-9.^-]/g, '');
    }

    function sanitizeUrl(value) {
        try {
            const parsed = new URL(String(value ?? ''), window.location.origin);
            if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                return parsed.href;
            }
        } catch (error) {
            return '';
        }
        return '';
    }

    function fetchJson(url, options = {}) {
        return fetch(url, options).then(response => {
            const contentType = response.headers.get('content-type') || '';
            const parser = contentType.includes('application/json')
                ? response.json()
                : response.text().then(text => ({ error: text || 'Unexpected response.' }));

            return parser.catch(() => ({})).then(payload => {
                if (!response.ok) {
                    throw new Error(payload.error || `Request failed (${response.status})`);
                }
                return payload;
            });
        });
    }

    function showError(target, message, options = {}) {
        const el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return;
        const textTarget = options.textTarget || el;
        textTarget.textContent = message || '';
        if (options.hiddenClass) {
            el.classList.remove(options.hiddenClass);
        } else {
            el.style.display = '';
        }
        (options.hide || []).forEach(item => {
            if (!item) return;
            if (options.hiddenClass) {
                item.classList.add(options.hiddenClass);
            } else {
                item.style.display = 'none';
            }
        });
    }

    window.StockScreenUtils = {
        escapeHtml,
        sanitizeSymbol,
        sanitizeUrl,
        fetchJson,
        showError,
    };
})();
