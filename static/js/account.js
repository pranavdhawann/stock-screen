// Account sign-in/sign-up modal and session state.
// Exposes window.StockScreenAuth = { state, open } and fires an
// 'auth:changed' event whenever the signed-in user changes.
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
    var accountMenu = document.getElementById('accountMenu');
    var accountDropdown = document.getElementById('accountDropdown');
    var accountDropdownEmail = document.getElementById('accountDropdownEmail');
    var accountDropdownPlan = document.getElementById('accountDropdownPlan');
    var accountDropdownPro = document.getElementById('accountDropdownPro');
    var accountDropdownSignOut = document.getElementById('accountDropdownSignOut');
    var fetchJson = (window.StockScreenUtils || {}).fetchJson;

    if (!modal || !form || !accountBtn || !fetchJson) return;

    var mode = 'login'; // or 'signup'
    var state = { authenticated: false, email: null };

    function emitChange() {
        window.dispatchEvent(new CustomEvent('auth:changed', { detail: state }));
    }

    // "GET PRO" is a waitlist prompt; an account that already has pro should
    // see its status instead of being asked to request what it holds. The
    // label lives in its own span so rewriting it can't clobber the nav
    // item's markup.
    var waitlistBtn = document.getElementById('waitlistBtn');
    var waitlistBtnLabel = document.getElementById('waitlistBtnLabel');

    function updateProBadge() {
        if (!waitlistBtn || !waitlistBtnLabel) return;
        if (state.plan === 'pro') {
            waitlistBtnLabel.textContent = 'Pro';
            waitlistBtn.title = 'Pro plan active - click to view your plan';
        } else {
            waitlistBtnLabel.textContent = 'Get Pro';
            waitlistBtn.title = '';
        }
    }

    // The dropdown hangs off the Profile nav item, so the item carries the
    // same .active treatment as a current page while its panel is open.
    function closeAccountDropdown() {
        if (!accountDropdown) return;
        accountDropdown.classList.remove('open');
        accountBtn.classList.remove('active');
        accountBtn.setAttribute('aria-expanded', 'false');
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
            if (accountDropdownEmail) accountDropdownEmail.textContent = state.email || '';
            if (accountDropdownPlan) {
                var isPro = state.plan === 'pro';
                accountDropdownPlan.textContent = isPro ? 'PRO' : 'FREE';
                accountDropdownPlan.classList.toggle('is-pro', isPro);
            }
        } else {
            if (accountBtnLabel) accountBtnLabel.textContent = 'Sign In';
            accountBtn.title = 'Sign in or create an account';
            closeAccountDropdown();
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

    // One nav item, two destinations: the sign-in modal when signed out,
    // the account panel when signed in.
    accountBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (!state.authenticated) {
            openModal();
            return;
        }
        if (!accountDropdown) return;
        var isOpen = accountDropdown.classList.toggle('open');
        accountBtn.classList.toggle('active', isOpen);
        accountBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    function signOut() {
        closeAccountDropdown();
        fetchJson('/api/auth/logout', { method: 'POST' })
            .catch(function() {})
            .then(function() { setState(false, null); });
    }

    if (accountDropdown) {
        document.addEventListener('click', function(e) {
            if (!accountDropdown.classList.contains('open')) return;
            if (accountMenu && !accountMenu.contains(e.target)) closeAccountDropdown();
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && accountDropdown.classList.contains('open')) closeAccountDropdown();
        });
    }
    if (accountDropdownSignOut) {
        accountDropdownSignOut.addEventListener('click', signOut);
    }
    if (accountDropdownPro) {
        accountDropdownPro.addEventListener('click', function() {
            closeAccountDropdown();
            if (waitlistBtn) waitlistBtn.click();
        });
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

    // Restore session state on page load.
    fetchJson('/api/auth/me')
        .then(function(data) { setState(data.authenticated, data.email, data.plan); })
        .catch(function() { setState(false, null); });

    window.StockScreenAuth = {
        get state() { return state; },
        open: openModal,
    };
})();
