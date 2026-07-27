/**
 * Profile page.
 *
 * The account panel used to be a dropdown anchored in the nav and the Pro
 * flow a pair of site-wide modals; both are sections of this page now, so
 * this file owns the plan catalogue and the payment-link request outright.
 *
 * No payment is handled here: submitting records the request and, when the
 * operator has configured one, surfaces a hosted checkout link the user
 * clicks themselves. Checkout happens on the provider's own page.
 *
 * Loaded only by profile.html, but every lookup is still null-guarded.
 */
(function() {
    var HIDDEN = 'idx-hidden';
    var EMAIL_MAX = 254;

    var loadingEl = document.getElementById('profileLoading');
    var signedOutEl = document.getElementById('profileSignedOut');
    var signedInEl = document.getElementById('profileSignedIn');
    var signInBtn = document.getElementById('profileSignInBtn');
    var emailEl = document.getElementById('profileEmail');
    var planBadge = document.getElementById('profilePlanBadge');
    var signOutBtn = document.getElementById('profileSignOutBtn');
    var proStatusEl = document.getElementById('profileProStatus');
    var plansLead = document.getElementById('profilePlansLead');

    var form = document.getElementById('profileProForm');
    var planOptions = document.getElementById('profilePlanOptions');
    var proEmailEl = document.getElementById('profileProEmail');
    var submitBtn = document.getElementById('profileProSubmit');
    var successEl = document.getElementById('profileProSuccess');
    var payLinkEl = document.getElementById('profileProPayLink');
    var errorEl = document.getElementById('profileProError');

    var utils = window.StockScreenUtils || {};
    var auth = window.StockScreenAuth;
    var fetchJson = utils.fetchJson;
    var escapeHtml = utils.escapeHtml;
    var sanitizeUrl = utils.sanitizeUrl;
    var trackEvent = utils.trackEvent || function() {};

    if (!signedInEl || !auth || !fetchJson || !escapeHtml) return;

    function toggle(el, visible) {
        if (el) el.classList.toggle(HIDDEN, !visible);
    }

    function fieldValue(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : '';
    }

    // The catalogue is public, so it loads on page load rather than waiting on
    // the session — the picker is the whole point of the "view pro plans"
    // link and must be there whoever followed it.
    function loadPlans() {
        if (!planOptions) return;
        fetchJson('/api/pro/plans').then(function(data) {
            var plans = (data && data.plans) || [];
            planOptions.innerHTML = plans.map(function(plan, index) {
                return '<label class="plan-option">' +
                    '<input type="radio" name="profileProPlan" value="' + escapeHtml(plan.code) + '"' +
                    (index === 0 ? ' checked' : '') + '>' +
                    '<span class="plan-option-body">' +
                    '<span class="plan-option-name">' + escapeHtml(plan.name) + '</span>' +
                    '<span class="plan-option-price">' + escapeHtml(plan.price) + '</span>' +
                    '<span class="plan-option-summary">' + escapeHtml(plan.summary) + '</span>' +
                    '</span></label>';
            }).join('');
        }).catch(function() {
            // Leave the list empty; submitting without a plan is rejected with
            // a clear message rather than silently failing.
            planOptions.innerHTML =
                '<div class="modal-error-text modal-error-text--inline">' +
                'Plans are unavailable right now. Please try again later.</div>';
        });
    }

    var PRO_LEAD = 'You\'re already on Pro. Requesting a plan below sends a fresh ' +
        'payment link — use it to switch plans or renew.';

    // Only the account cards and the lead copy depend on the session; the plan
    // picker itself is the same for everyone.
    function render(state) {
        var isPro = state.authenticated && state.plan === 'pro';

        toggle(loadingEl, false);
        toggle(signedOutEl, !state.authenticated);
        toggle(signedInEl, state.authenticated);
        toggle(proStatusEl, isPro);

        if (plansLead && isPro) plansLead.textContent = PRO_LEAD;

        if (!state.authenticated) return;

        if (emailEl) emailEl.textContent = state.email || '';
        if (planBadge) {
            planBadge.textContent = isPro ? 'PRO' : 'FREE';
            planBadge.classList.toggle('is-pro', isPro);
        }
        // Pre-fill the address the account is already known by; the field
        // stays editable in case the payment should go elsewhere.
        if (proEmailEl && !proEmailEl.value) proEmailEl.value = state.email || '';
    }

    if (signInBtn) {
        signInBtn.addEventListener('click', function() { auth.open(); });
    }
    if (signOutBtn) {
        signOutBtn.addEventListener('click', function() {
            signOutBtn.disabled = true;
            auth.signOut().then(function() { signOutBtn.disabled = false; });
        });
    }

    loadPlans();

    // account.js owns the session; re-render whenever it changes, and wait for
    // the initial /api/auth/me rather than flashing the signed-out state.
    window.addEventListener('auth:changed', function(e) { render(e.detail); });
    auth.ready.then(function() { render(auth.state); });

    if (!form || !submitBtn || !errorEl || !successEl) return;

    function showError(message) {
        utils.showError(errorEl, message);
    }

    function setSubmitting(isSubmitting) {
        submitBtn.disabled = isSubmitting;
        submitBtn.textContent = isSubmitting ? 'SENDING...' : 'REQUEST PAYMENT LINK';
    }

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        errorEl.style.display = 'none';

        var checked = form.querySelector('input[name="profileProPlan"]:checked');
        var plan = checked ? checked.value : '';
        if (!plan) {
            showError('Please choose a plan.');
            return;
        }

        var email = fieldValue('profileProEmail');
        if (email.length > EMAIL_MAX || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
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
                website: fieldValue('profileProWebsite'),
                company: fieldValue('profileProCompany'),
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
