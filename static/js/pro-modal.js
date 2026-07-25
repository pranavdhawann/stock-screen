/**
 * Pro plans modal ("GET PRO" in the nav).
 *
 * Picks a plan, records the request server-side, and — when the operator has
 * configured a hosted checkout URL for that plan — surfaces it as a link the
 * user clicks themselves. Nothing here touches card details or takes payment;
 * checkout happens entirely on the provider's own page.
 *
 * Mirrors contact.js: same modal-overlay markup, same open/close/Escape
 * handling, same honeypot pair.
 *
 * Loaded from base.html on every page, so every lookup is null-guarded and
 * the whole thing no-ops if the modal markup is absent.
 */
(function() {
    var modal = document.getElementById('waitlistModal');
    var form = document.getElementById('waitlistForm');
    var planOptions = document.getElementById('wlPlanOptions');
    var successEl = document.getElementById('wlSuccess');
    var payLinkEl = document.getElementById('wlPayLink');
    var errorEl = document.getElementById('wlError');
    var submitBtn = document.getElementById('wlSubmitBtn');
    var closeBtn = document.getElementById('waitlistModalClose');
    var emailMax = 254;
    var utils = window.StockScreenUtils || {};
    var fetchJson = utils.fetchJson;
    var escapeHtml = utils.escapeHtml;
    var sanitizeUrl = utils.sanitizeUrl;
    var trackEvent = utils.trackEvent || function() {};

    if (!modal || !form || !successEl || !errorEl || !submitBtn || !fetchJson) return;

    // Fetched once on first open, then reused — the catalogue only changes on
    // deploy, and re-fetching on every open would flash an empty list.
    var plansLoaded = false;

    function fieldValue(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : '';
    }

    function showError(message) {
        utils.showError(errorEl, message);
    }

    function setSubmitting(isSubmitting) {
        submitBtn.disabled = isSubmitting;
        submitBtn.textContent = isSubmitting ? 'SENDING...' : 'REQUEST PAYMENT LINK';
    }

    function selectedPlan() {
        var checked = form.querySelector('input[name="proPlan"]:checked');
        return checked ? checked.value : '';
    }

    function renderPlans(plans) {
        if (!planOptions) return;
        if (!plans || plans.length === 0) {
            planOptions.innerHTML = '';
            return;
        }
        planOptions.innerHTML = plans.map(function(plan, index) {
            var code = escapeHtml(plan.code);
            return '<label class="plan-option">' +
                '<input type="radio" name="proPlan" value="' + code + '"' +
                (index === 0 ? ' checked' : '') + '>' +
                '<span class="plan-option-body">' +
                '<span class="plan-option-name">' + escapeHtml(plan.name) + '</span>' +
                '<span class="plan-option-price">' + escapeHtml(plan.price) + '</span>' +
                '<span class="plan-option-summary">' + escapeHtml(plan.summary) + '</span>' +
                '</span></label>';
        }).join('');
    }

    function loadPlans() {
        if (plansLoaded || !planOptions) return;
        fetchJson('/api/pro/plans')
            .then(function(data) {
                renderPlans((data && data.plans) || []);
                plansLoaded = true;
            })
            .catch(function() {
                // Leave the list empty; submitting without a plan is rejected
                // with a clear message rather than silently failing.
                planOptions.innerHTML =
                    '<div class="modal-error-text modal-error-text--inline">' +
                    'Plans are unavailable right now. Please try again later.</div>';
            });
    }

    window.openWaitlistModal = function() {
        form.style.display = '';
        successEl.style.display = 'none';
        errorEl.style.display = 'none';
        if (payLinkEl) payLinkEl.style.display = 'none';
        form.reset();
        setSubmitting(false);
        loadPlans();
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

    // Pro status modal: shown instead of the waitlist to users who already
    // hold a Pro plan.
    var statusModal = document.getElementById('proStatusModal');
    var statusCloseBtn = document.getElementById('proStatusModalClose');
    if (statusModal) {
        window.openProStatusModal = function() {
            statusModal.style.display = 'flex';
        };
        window.closeProStatusModal = function() {
            statusModal.style.display = 'none';
        };
        if (statusCloseBtn) {
            statusCloseBtn.addEventListener('click', window.closeProStatusModal);
        }
        statusModal.addEventListener('click', function(e) {
            if (e.target === statusModal) window.closeProStatusModal();
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && statusModal.style.display === 'flex') window.closeProStatusModal();
        });
    }

    // Any element can open this, not just the nav button, so pages can add
    // their own upgrade CTAs without touching this file. Accounts that
    // already hold Pro see their status instead of being asked to request
    // what they already have.
    document.querySelectorAll('[data-action="open-waitlist-modal"]').forEach(function(trigger) {
        trigger.addEventListener('click', function() {
            var auth = window.StockScreenAuth;
            if (auth && auth.state.plan === 'pro' && window.openProStatusModal) {
                window.openProStatusModal();
            } else {
                window.openWaitlistModal();
            }
        });
    });

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        errorEl.style.display = 'none';

        var plan = selectedPlan();
        if (!plan) {
            showError('Please choose a plan.');
            return;
        }

        var email = fieldValue('wlEmail');
        if (email.length > emailMax || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
            showError('Please enter a valid email.');
            return;
        }

        setSubmitting(true);
        trackEvent('pro-payment-link-request', { plan: plan });
        fetchJson('/api/pro/payment-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email,
                plan: plan,
                website: fieldValue('wlWebsite'),
                company: fieldValue('wlCompany'),
            }),
        }).then(function(data) {
            form.style.display = 'none';
            successEl.textContent = (data && data.message) || 'Request received.';
            successEl.style.display = '';

            // The server only ever sends an https URL, but re-check here too:
            // this value goes straight into an href.
            var link = sanitizeUrl((data && data.payment_link) || '');
            if (payLinkEl && link) {
                payLinkEl.href = link;
                payLinkEl.style.display = '';
            }
        }).catch(function(error) {
            showError(error.message || 'Could not request a payment link. Please try again.');
            setSubmitting(false);
        });
    });
})();
