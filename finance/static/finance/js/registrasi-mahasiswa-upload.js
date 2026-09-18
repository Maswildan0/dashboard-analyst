/* Excel upload -> validate -> preview -> confirm flow.
 * No file is committed to the database before the explicit confirmation.
 */
(function () {
    'use strict';

    var form = document.getElementById('regm-upload-form');
    if (!form) return;

    var modal = document.getElementById('regm-upload-modal');
    var input = form.querySelector('input[type="file"]');
    var message = document.getElementById('regm-upload-message');
    var preview = document.getElementById('regm-preview');
    var previewBody = document.getElementById('regm-preview-body');
    var previewSummary = document.getElementById('regm-preview-summary');
    var previewLimit = document.getElementById('regm-preview-limit');
    var previewButton = document.getElementById('regm-preview-btn');
    var confirmButton = document.getElementById('regm-confirm-btn');
    var backButton = document.getElementById('regm-preview-back');
    var token = '';

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function csrf() {
        var el = form.querySelector('input[name="csrfmiddlewaretoken"]');
        return el ? el.value : '';
    }

    function showMessage(text) {
        message.textContent = text || '';
        message.hidden = !text;
    }

    function summaryCard(label, value, cls) {
        return '<div class="regm-preview-stat ' + (cls || '') + '">' +
            '<div class="regm-preview-stat-label">' + escapeHtml(label) + '</div>' +
            '<div class="regm-preview-stat-value">' + escapeHtml(value) + '</div>' +
            '</div>';
    }

    function renderSummary(summary) {
        previewSummary.innerHTML = [
            summaryCard('Total Rows', summary.total),
            summaryCard('Valid', summary.valid, 'regm-stat-valid'),
            summaryCard('New', summary.new),
            summaryCard('Update', summary.update),
            summaryCard('Error', summary.error, summary.error ? 'regm-stat-error' : ''),
        ].join('');
    }

    function renderRows(rows) {
        previewBody.innerHTML = rows.map(function (row) {
            var statusClass = 'regm-status-' + row.status.toLowerCase();
            return '<tr>' +
                '<td><span class="regm-status ' + statusClass + '">' + escapeHtml(row.status) + '</span></td>' +
                '<td>' + escapeHtml(row.study_program_code) + '</td>' +
                '<td>' + escapeHtml(row.faculty_name) + '</td>' +
                '<td>' + escapeHtml(row.study_program_name) + '</td>' +
                '<td class="regm-num">' + escapeHtml(row.year) + '</td>' +
                '<td class="regm-num">' + escapeHtml(row.tariff == null ? '-' : 'Rp' + Number(row.tariff).toLocaleString('id-ID')) + '</td>' +
                '<td class="regm-num">' + escapeHtml(Number(row.quota).toLocaleString('id-ID')) + '</td>' +
                '<td class="regm-num">' + escapeHtml(Number(row.registration).toLocaleString('id-ID')) + '</td>' +
                '<td class="regm-preview-error">' + escapeHtml(row.validation || '-') + '</td>' +
                '</tr>';
        }).join('');
    }

    function openModal() {
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('regm-modal-open');
        if (input) input.focus();
    }

    function closeModal() {
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('regm-modal-open');
        showMessage('');
        preview.hidden = true;
        confirmButton.disabled = true;
        token = '';
        form.reset();
    }

    function previewFile(event) {
        event.preventDefault();
        showMessage('');
        var file = input && input.files ? input.files[0] : null;
        if (!file) {
            showMessage('Pilih file .xlsx terlebih dahulu.');
            return;
        }
        if (!file.name.toLowerCase().endsWith('.xlsx')) {
            showMessage('File harus berformat .xlsx.');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            showMessage('Ukuran file maksimal 10 MB.');
            return;
        }

        previewButton.disabled = true;
        previewButton.textContent = 'Memvalidasi...';
        var data = new FormData(form);
        fetch(form.dataset.previewUrl, {
            method: 'POST', body: data,
            headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
        })
            .then(function (response) {
                return response.json().then(function (body) {
                    if (!response.ok || !body.ok) throw new Error(body.message || 'Preview gagal.');
                    return body;
                });
            })
            .then(function (body) {
                token = body.token;
                renderSummary(body.summary);
                renderRows(body.rows || []);
                previewLimit.textContent = body.summary.total > (body.rows || []).length
                    ? 'Menampilkan maksimal 100 baris pertama dari file.' : '';
                confirmButton.disabled = !body.can_confirm;
                preview.hidden = false;
            })
            .catch(function (error) { showMessage(error.message); })
            .finally(function () {
                previewButton.disabled = false;
                previewButton.textContent = 'Preview Data';
            });
    }

    function confirmImport() {
        if (!token || confirmButton.disabled) return;
        confirmButton.disabled = true;
        confirmButton.textContent = 'Mengimpor...';
        var body = new URLSearchParams({token: token});
        fetch(form.dataset.confirmUrl, {
            method: 'POST', body: body,
            headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
        })
            .then(function (response) {
                return response.json().then(function (payload) {
                    if (!response.ok || !payload.ok) throw new Error(payload.message || 'Import gagal.');
                    return payload;
                });
            })
            .then(function () { window.location.reload(); })
            .catch(function (error) {
                showMessage(error.message);
                confirmButton.disabled = false;
                confirmButton.textContent = 'Import Data';
            });
    }

    document.getElementById('regm-upload-open').addEventListener('click', openModal);
    document.querySelectorAll('[data-regm-close]').forEach(function (button) {
        button.addEventListener('click', closeModal);
    });
    form.addEventListener('submit', previewFile);
    confirmButton.addEventListener('click', confirmImport);
    backButton.addEventListener('click', function () {
        preview.hidden = true;
        confirmButton.disabled = true;
        token = '';
        showMessage('');
        input.value = '';
        input.focus();
    });
})();
