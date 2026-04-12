/* FaxNode – Frontend JS */

// --- SSE ---
var es = new EventSource('/events');

es.addEventListener('new_fax', function(e) {
    var d = JSON.parse(e.data);
    var sender = d.sender_name || d.phone_number;
    showToast('Neues Fax', sender + ' — ' + d.received_at, '/faxe/' + d.id);
    playNotificationSound();
    showBrowserNotification('Neues Fax', sender + ' — ' + d.received_at);
    if (location.pathname === '/faxe') location.reload();
});

es.addEventListener('status_changed', function(e) {
    var d = JSON.parse(e.data);
    // Update badge in list view
    var badges = document.querySelectorAll('.fax-status[data-fax-id="' + d.fax_id + '"]');
    badges.forEach(function(badge) {
        badge.textContent = d.status_label;
        badge.className = 'fax-status badge badge-' + d.status;
    });
    // Update select in detail view
    var sel = document.querySelector('#status-select[data-fax-id="' + d.fax_id + '"]');
    if (sel && sel !== document.activeElement) {
        sel.value = d.status;
        sel.className = 'status-select badge-' + d.status;
    }
});

es.addEventListener('note_added', function(e) {
    var d = JSON.parse(e.data);
    var list = document.getElementById('notes-list');
    if (!list) return;
    var faxId = document.querySelector('#note-form')?.dataset.faxId;
    if (faxId != d.fax_id) return;
    var noNotes = document.getElementById('no-notes');
    if (noNotes) noNotes.remove();
    var note = document.createElement('div');
    note.className = 'note';
    note.innerHTML = '<div class="note-header"><span class="note-author">' + escapeHtml(d.author) +
        '</span><span class="note-date mono-sm">gerade eben</span></div>' +
        '<div class="note-message">' + escapeHtml(d.message) + '</div>';
    list.appendChild(note);
    list.scrollTop = list.scrollHeight;
});

es.addEventListener('ocr_complete', function(e) {
    if (location.pathname === '/faxe') location.reload();
});

// --- Status Change ---
document.addEventListener('change', function(e) {
    if (e.target.id === 'status-select') {
        var faxId = e.target.dataset.faxId;
        var status = e.target.value;
        fetch('/api/fax/' + faxId + '/status', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: status})
        });
        e.target.className = 'status-select badge-' + status;
    }
});

// --- Notes ---
document.addEventListener('submit', function(e) {
    if (e.target.id === 'note-form') {
        e.preventDefault();
        var form = e.target;
        var faxId = form.dataset.faxId;
        var author = form.querySelector('[name=author]').value.trim() || 'Mitarbeiter';
        var message = form.querySelector('[name=message]').value.trim();
        if (!message) return;
        fetch('/api/fax/' + faxId + '/notiz', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({author: author, message: message})
        });
        form.querySelector('[name=message]').value = '';
    }
});

// --- Print ---
function printFax(faxId) {
    fetch('/api/drucker').then(function(r) { return r.json(); }).then(function(printers) {
        var names = Object.keys(printers);
        if (names.length === 0) { showToast('Fehler', 'Keine Drucker gefunden'); return; }
        var printer = names.length === 1 ? names[0] : prompt('Drucker waehlen:\n' + names.join('\n'));
        if (!printer) return;
        fetch('/api/fax/' + faxId + '/drucken', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({printer: printer, copies: 1})
        }).then(function(r) { return r.json(); }).then(function(d) {
            showToast(d.ok ? 'Druckauftrag gesendet' : 'Fehler', d.error || printer);
        });
    });
}

// --- Address Book ---
function toggleAddressForm() {
    var c = document.getElementById('address-form-container');
    c.style.display = c.style.display === 'none' ? 'block' : 'none';
}

function saveAddress(e) {
    e.preventDefault();
    var form = e.target;
    var data = {
        phone_number: form.querySelector('[name=phone_number]').value.trim(),
        name: form.querySelector('[name=name]').value.trim(),
        notes: form.querySelector('[name=notes]').value.trim()
    };
    fetch('/api/adressbuch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(function() { location.reload(); });
}

function deleteAddress(id) {
    if (!confirm('Eintrag wirklich loeschen?')) return;
    fetch('/api/adressbuch/' + id, {method: 'DELETE'}).then(function() { location.reload(); });
}

// --- Print Rules ---
function toggleRuleForm() {
    var c = document.getElementById('rule-form-container');
    var btn = document.getElementById('add-rule-btn');
    c.style.display = c.style.display === 'none' ? 'block' : 'none';
    btn.style.display = c.style.display === 'none' ? 'inline-flex' : 'none';
}

function saveRule(e) {
    e.preventDefault();
    var form = e.target;
    var data = {
        phone_number: form.querySelector('[name=phone_number]').value.trim(),
        printer_name: form.querySelector('[name=printer_name]').value,
        copies: parseInt(form.querySelector('[name=copies]').value) || 1
    };
    fetch('/api/druckregel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(function() { location.reload(); });
}

function deleteRule(id) {
    if (!confirm('Regel wirklich loeschen?')) return;
    fetch('/api/druckregel/' + id, {method: 'DELETE'}).then(function() { location.reload(); });
}

// --- Notifications ---
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}

function showBrowserNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {body: body, icon: '/static/sounds/notification.mp3'});
    }
}

function playNotificationSound() {
    try { new Audio('/static/sounds/notification.mp3').play(); } catch(e) {}
}

// --- Toast ---
function showToast(title, body, link) {
    var container = document.getElementById('toast-container');
    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = '<div class="toast-title">' + escapeHtml(title) + '</div>' +
        '<div class="toast-body">' + escapeHtml(body) + '</div>';
    if (link) toast.onclick = function() { location.href = link; };
    container.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 5000);
}

// --- Helpers ---
function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
