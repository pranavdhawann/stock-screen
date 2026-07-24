/**
 * Paid-tier waitlist modal ("GET PRO" in the nav).
 *
 * Mirrors contact.js: same modal-overlay markup, same open/close/Escape
 * handling, same honeypot pair. Distinct from watchlist.js, which is the
 * per-user saved-symbols feature — this file is the *wait*list.
 *
 * Loaded from base.html on every page, so every lookup is null-guarded and
 * the whole thing no-ops if the modal markup is absent.
 */
(function() {
    var modal = document.getElementById('waitlistModal');
    var form = document.getElementById('waitlistForm');
    var successEl = document.getElementById('wlSuccess');
    var errorEl = document.getElementById('wlError');
    var submitBtn = document.getElementById('wlSubmitBtn');
    var closeBtn = document.getElementById('waitlistModalClose');
    var emailMax = 254;
    var utils = window.StockScreenUtils || {};
    var fetchJson = utils.fetchJson;

    if (!modal || !form || !successEl || !errorEl || !submitBtn || !fetchJson) return;

    function fieldValue(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : '';
    }

    function showError(message) {
        utils.showError(errorEl, message);
    }

    function setSubmitting(isSubmitting) {
        submitBtn.disabled = isSubmitting;
        submitBtn.textContent = isSubmitting ? 'SENDING...' : 'REQUEST ACCESS';
    }

    window.openWaitlistModal = function() {
        form.style.display = '';
        successEl.style.display = 'none';
        errorEl.style.display = 'none';
        form.reset();
        setSubmitting(false);
        modal.style.display = 'flex';
        var emailInput = document.getElementById('wlEmail');
        if (emailInput) emailInput.focus();
    };
    window.closeWaitlistModal = function() {
        modal.style.display = 'none';
    };

    if (closeBtn) {
        closeBtn.addEventListener('click', window.closeWaitlistModal);
    }
    modal.addEventListener('click', function(e) {
        if (e.target === modal) window.closeWaitlistModal();
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.style.display === 'flex') window.closeWaitlistModal();
    });

    // Any element can open the modal, not just the nav button, so pages can
    // add their own upgrade CTAs without touching this file.
    document.querySelectorAll('[data-action="open-waitlist-modal"]').forEach(function(trigger) {
        trigger.addEventListener('click', window.openWaitlistModal);
    });

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        errorEl.style.display = 'none';

        var email = fieldValue('wlEmail');
        if (email.length > emailMax || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
            showError('Please enter a valid email.');
            return;
        }

        setSubmitting(true);
        fetchJson('/api/waitlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email,
                website: fieldValue('wlWebsite'),
                company: fieldValue('wlCompany'),
            }),
        }).then(function(data) {
            form.style.display = 'none';
            // The server returns the same message whether the address is new
            // or already on the list — don't try to distinguish them here.
            successEl.textContent = (data && data.message) || "You're on the list.";
            successEl.style.display = '';
        }).catch(function(error) {
            showError(error.message || 'Could not join the waitlist. Please try again.');
            setSubmitting(false);
        });
    });
})();
