/**
 * Market segmented toggle (USA / INDIA).
 *
 * Keeps the hidden `#marketSelect` <select> as the single source of truth
 * that every other page script reads/listens to. This file only:
 *   1. Initialises the visible pill buttons from the select's current value.
 *   2. On click, updates the select's value and dispatches a native
 *      `change` event on it (bubbling), then updates pressed/active state.
 *
 * Runs on every page (loaded from base.html), so every lookup is null-guarded.
 */
(function () {
    'use strict';

    function init() {
        var select = document.getElementById('marketSelect');
        var toggle = document.getElementById('marketToggle');
        if (!select || !toggle) {
            return;
        }

        var buttons = toggle.querySelectorAll('.market-toggle-btn[data-market]');
        if (!buttons || !buttons.length) {
            return;
        }

        function syncButtons(value) {
            buttons.forEach(function (btn) {
                var isActive = btn.getAttribute('data-market') === value;
                btn.classList.toggle('active', isActive);
                btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
            });
        }

        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var market = btn.getAttribute('data-market');
                if (!market || select.value === market) {
                    syncButtons(select.value);
                    return;
                }
                select.value = market;
                syncButtons(market);
                var track = (window.StockScreenUtils || {}).trackEvent;
                if (track) track('switch-market', { market: market });
                select.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });

        // Initialise from whatever the select's current value is on load.
        syncButtons(select.value);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
