(function() {
    var modal = document.getElementById('contactModal');
    var form = document.getElementById('contactModalForm');
    var successEl = document.getElementById('cmSuccess');
    var errorEl = document.getElementById('cmError');
    var submitBtn = document.getElementById('cmSubmitBtn');
    var closeBtn = document.getElementById('contactModalClose');
    var nameMax = 120;
    var emailMax = 254;
    var messageMax = 3000;
    var utils = window.StockScreenUtils || {};
    var fetchJson = utils.fetchJson;

    // fetchJson is guarded alongside the DOM lookups: utils.js is loaded
    // before this file in base.html, but a load failure there would otherwise
    // surface as a TypeError inside the submit handler rather than a no-op.
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
        submitBtn.textContent = isSubmitting ? 'SENDING...' : 'SEND MESSAGE';
    }

    window.openContactModal = function() {
        form.style.display = '';
        successEl.style.display = 'none';
        errorEl.style.display = 'none';
        form.reset();
        setSubmitting(false);
        modal.style.display = 'flex';
    };
    window.closeContactModal = function() {
        modal.style.display = 'none';
    };

    if (closeBtn) {
        closeBtn.addEventListener('click', window.closeContactModal);
    }
    modal.addEventListener('click', function(e) {
        if (e.target === modal) window.closeContactModal();
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.style.display === 'flex') window.closeContactModal();
    });

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        errorEl.style.display = 'none';

        var name = fieldValue('cmName');
        var email = fieldValue('cmEmail');
        var message = fieldValue('cmMessage');
        var website = fieldValue('cmWebsite');
        var company = fieldValue('cmCompany');

        if (!name || !email || !message) {
            showError('All fields are required.');
            return;
        }
        if (name.length > nameMax) {
            showError('Name must be 120 characters or fewer.');
            return;
        }
        if (email.length > emailMax || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
            showError('Please enter a valid email.');
            return;
        }
        if (message.length > messageMax) {
            showError('Message must be 3000 characters or fewer.');
            return;
        }

        setSubmitting(true);
        fetchJson('/api/contact', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                email: email,
                message: message,
                website: website,
                company: company,
            }),
        }).then(function() {
            form.style.display = 'none';
            successEl.style.display = '';
        }).catch(function(error) {
            showError(error.message || 'Failed to send. Please try again.');
            setSubmitting(false);
        });
    });
})();
