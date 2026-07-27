// Account sign-in/sign-up modal and session state.
// Exposes window.StockScreenAuth = { state, open, signOut, ready } and fires
// an 'auth:changed' event whenever the signed-in user changes.
(function() {
    var modal = document.getElementById('authModal');
    var form = document.getElementById('authForm');
    var titleEl = document.getElementById('authModalTitle');
    var emailEl = document.getElementById('authEmail');
    var passwordEl = document.getElementById('authPassword');
    var submitBtn = document.getElementById('authSubmitBtn');
    var errorEl = document.getElementById('authError');
    var togglePrompt = document.getElementById('authTogglePrompt');
    var toggleBtn = document.getElementById('authToggleMode');
    var closeBtn = document.getElementById('authModalClose');
    var accountBtn = document.getElementById('accountBtn');
    var accountBtnLabel = document.getElementById('accountBtnLabel');
    var navPlanBadge = document.getElementById('navPlanBadge');
    var fetchJson = (window.StockScreenUtils || {}).fetchJson;

    if (!modal || !form || !accountBtn || !fetchJson) return;

    var mode = 'login'; // or 'signup'
    var state = { authenticated: false, email: null };

    function emitChange() {
        window.dispatchEvent(new CustomEvent('auth:changed', { detail: state }));
    }

    // The plan is reported next to the Profile item as a badge, not a
    // control — it states what you have; upgrading happens on /profile.
    // Hidden while signed out, when there is no plan to report.
    function updateProBadge() {
        if (!navPlanBadge) return;
        var isPro = state.plan === 'pro';
        navPlanBadge.hidden = !state.authenticated;
        navPlanBadge.textContent = isPro ? 'Pro' : 'Free';
        navPlanBadge.classList.toggle('is-pro', isPro);
    }

    function setState(authenticated, email, plan) {
        state = {
            authenticated: !!authenticated,
            email: email || null,
            plan: (authenticated && plan) || 'free',
        };
        if (state.authenticated) {
            if (accountBtnLabel) accountBtnLabel.textContent = 'Profile';
            accountBtn.title = 'Signed in as ' + state.email;
        } else {
            if (accountBtnLabel) accountBtnLabel.textContent = 'Sign In';
            accountBtn.title = 'Sign in or create an account';
        }
        updateProBadge();
        emitChange();
    }

    function setMode(next) {
        mode = next;
        var isSignup = mode === 'signup';
        titleEl.textContent = isSignup ? 'CREATE ACCOUNT' : 'SIGN IN';
        submitBtn.textContent = isSignup ? 'CREATE ACCOUNT' : 'SIGN IN';
        togglePrompt.textContent = isSignup ? 'Already registered?' : 'No account yet?';
        toggleBtn.textContent = isSignup ? 'Sign in' : 'Create one';
        passwordEl.setAttribute('autocomplete', isSignup ? 'new-password' : 'current-password');
        errorEl.style.display = 'none';
    }

    function showError(message) {
        errorEl.textContent = message;
        errorEl.style.display = '';
    }

    function setSubmitting(isSubmitting) {
        submitBtn.disabled = isSubmitting;
        if (isSubmitting) submitBtn.textContent = 'WORKING...';
        else setMode(mode);
    }

    function openModal() {
        form.reset();
        setMode('login');
        modal.style.display = 'flex';
        emailEl.focus();
    }

    function closeModal() {
        modal.style.display = 'none';
    }

    // The nav item is a real link to /profile. Signed out there is nothing to
    // show there yet, so the click is intercepted and the auth modal opens
    // instead — the href stays as the no-JS fallback.
    accountBtn.addEventListener('click', function(e) {
        if (state.authenticated) return;
        e.preventDefault();
        openModal();
    });

    function signOut() {
        return fetchJson('/api/auth/logout', { method: 'POST' })
            .catch(function() {})
            .then(function() { setState(false, null); });
    }

    closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', function(e) {
        if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.style.display === 'flex') closeModal();
    });
    toggleBtn.addEventListener('click', function() {
        setMode(mode === 'login' ? 'signup' : 'login');
    });

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        errorEl.style.display = 'none';

        var email = emailEl.value.trim();
        var password = passwordEl.value;
        if (!email || password.length < 8) {
            showError('Enter your email and a password of at least 8 characters.');
            return;
        }

        setSubmitting(true);
        fetchJson(mode === 'signup' ? '/api/auth/signup' : '/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password }),
        }).then(function(data) {
            setSubmitting(false);
            // Event name only - never the address. Umami is cookieless and
            // this keeps it free of anything that identifies a person.
            var track = (window.StockScreenUtils || {}).trackEvent;
            if (track) track(mode === 'signup' ? 'account-signup' : 'account-login');
            setState(true, data.email, data.plan);
            closeModal();
        }).catch(function(error) {
            setSubmitting(false);
            showError(error.message || 'Unable to sign in right now.');
        });
    });

    // Restore session state on page load. Pages that render differently for
    // signed-in users (the profile page) wait on `ready` rather than assuming
    // the pre-fetch default of signed-out is the truth.
    var ready = fetchJson('/api/auth/me')
        .then(function(data) { setState(data.authenticated, data.email, data.plan); })
        .catch(function() { setState(false, null); });

    window.StockScreenAuth = {
        get state() { return state; },
        open: openModal,
        ready: ready,
        // Sign-out lives on the profile page now, but the session call and the
        // state broadcast stay here so there is one owner of both.
        signOut: signOut,
    };
})();
