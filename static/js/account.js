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
    var fetchJson = (window.StockScreenUtils || {}).fetchJson;

    if (!modal || !form || !accountBtn || !fetchJson) return;

    var mode = 'login'; // or 'signup'
    var state = { authenticated: false, email: null };

    function emitChange() {
        window.dispatchEvent(new CustomEvent('auth:changed', { detail: state }));
    }

    function setState(authenticated, email) {
        state = { authenticated: !!authenticated, email: email || null };
        if (state.authenticated) {
            var name = String(state.email || '').split('@')[0];
            accountBtn.textContent = 'SIGN OUT · ' + name.slice(0, 14).toUpperCase();
            accountBtn.title = 'Signed in as ' + state.email + ' — click to sign out';
        } else {
            accountBtn.textContent = 'SIGN IN';
            accountBtn.title = 'Sign in or create an account';
        }
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

    accountBtn.addEventListener('click', function() {
        if (!state.authenticated) {
            openModal();
            return;
        }
        fetchJson('/api/auth/logout', { method: 'POST' })
            .catch(function() {})
            .then(function() { setState(false, null); });
    });

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
            setState(true, data.email);
            closeModal();
        }).catch(function(error) {
            setSubmitting(false);
            showError(error.message || 'Unable to sign in right now.');
        });
    });

    // Restore session state on page load.
    fetchJson('/api/auth/me')
        .then(function(data) { setState(data.authenticated, data.email); })
        .catch(function() { setState(false, null); });

    window.StockScreenAuth = {
        get state() { return state; },
        open: openModal,
    };
})();
