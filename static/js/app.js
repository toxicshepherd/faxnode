/* FaxNode – Frontend JS */

// --- Unread Counter ---
var _unreadCount = (typeof UNREAD_COUNT !== 'undefined') ? UNREAD_COUNT : 0;
function updateTabTitle() {
    var base = 'FaxNode';
    document.title = _unreadCount > 0 ? '(' + _unreadCount + ') ' + base : base;
}
updateTabTitle();
setInterval(function() {
    fetch('/api/unread').then(function(r) { return r.json(); }).then(function(d) {
        _unreadCount = d.count;
        updateTabTitle();
    }).catch(function() {});
}, 30000);

// --- Date Formatting ---
function formatDate(str) {
    if (!str) return '';
    // "2026-03-12T08:30:00" or "2026-03-12 08:30:00" -> "12.03.2026 08:30"
    var m = str.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    if (m) return m[3] + '.' + m[2] + '.' + m[1] + ' ' + m[4] + ':' + m[5];
    return str.replace('T', ' ');
}

// --- SSE ---
var es = new EventSource('/events');

es.addEventListener('error', function() {
    // EventSource reconnects automatisch, aber wir loggen es
    console.warn('SSE-Verbindung unterbrochen, versuche erneut...');
});

es.addEventListener('new_fax', function(e) {
    var d = JSON.parse(e.data);
    var sender = d.sender_name || d.phone_number;
    _unreadCount++;
    updateTabTitle();
    showToast('Neues Fax', sender + ' — ' + d.received_at, '/faxe/' + d.id);
    playNotificationSound();
    showBrowserNotification('Neues Fax', sender + ' — ' + d.received_at);
    // Neue Fax-Karte in die Liste einfuegen statt reload
    if (location.pathname === '/faxe' && typeof renderFaxCard === 'function') {
        var list = document.getElementById('fax-list');
        var empty = document.getElementById('empty-state');
        if (empty) empty.remove();
        if (list) list.insertAdjacentHTML('afterbegin', renderFaxCard(d));
    }
});

es.addEventListener('status_changed', function(e) {
    var d = JSON.parse(e.data);
    // Update status buttons in list and detail view
    document.querySelectorAll('.status-btns[data-fax-id="' + d.fax_id + '"]').forEach(function(container) {
        container.querySelectorAll('.status-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === d.status);
        });
    });
    // Unread-Counter sofort aktualisieren
    fetch('/api/unread').then(function(r) { return r.json(); }).then(function(u) {
        _unreadCount = u.count;
        updateTabTitle();
    });
});

es.addEventListener('category_changed', function(e) {
    var d = JSON.parse(e.data);
    var sel = document.querySelector('#category-select[data-fax-id="' + d.fax_id + '"]');
    if (sel && sel !== document.activeElement) sel.value = d.category;
    // Kategorie-Badge in der Liste aktualisieren
    var card = document.querySelector('.fax-card-row[data-fax-id="' + d.fax_id + '"]');
    if (card) {
        var badge = card.querySelector('.cat-badge');
        if (badge) {
            badge.className = 'cat-badge cat-' + d.category;
            badge.textContent = d.category_label;
        }
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
    var d = JSON.parse(e.data);
    // Vorschau-Text in der Liste aktualisieren falls vorhanden
    var card = document.querySelector('.fax-card-row[data-fax-id="' + d.fax_id + '"]');
    if (card && d.ocr_text) {
        var preview = card.querySelector('.fax-card-preview');
        var txt = d.ocr_text.length > 150 ? d.ocr_text.substring(0, 150) + '...' : d.ocr_text;
        if (preview) {
            preview.textContent = txt;
        } else {
            var content = card.querySelector('.fax-card-content');
            if (content) content.insertAdjacentHTML('beforeend', '<div class="fax-card-preview text-muted">' + escapeHtml(txt) + '</div>');
        }
        // Thumbnail aktualisieren
        var thumb = card.querySelector('.fax-card-thumb');
        if (thumb && d.fax_id) {
            var placeholder = thumb.querySelector('.thumb-placeholder');
            if (placeholder) {
                placeholder.outerHTML = '<img src="/static/thumbnails/' + d.fax_id + '.png" alt="Vorschau" loading="lazy">';
            }
        }
    }
});

es.addEventListener('fax_printed', function(e) {
    var d = JSON.parse(e.data);
    // Print-Indikator in der Liste hinzufuegen
    var card = document.querySelector('.fax-card-row[data-fax-id="' + d.fax_id + '"]');
    if (card) {
        var header = card.querySelector('.fax-card-header');
        if (header && !header.querySelector('.print-indicator')) {
            var badge = header.querySelector('.cat-badge');
            if (badge) badge.insertAdjacentHTML('beforebegin', '<span class="print-indicator" title="Gedruckt auf ' + escapeHtml(d.printer) + '">&#9113;</span>');
        }
    }
    // Print-Status in der Detailansicht aktualisieren
    var statusEl = document.getElementById('print-status');
    if (statusEl) {
        statusEl.innerHTML = '<span class="print-indicator">&#10003; ' + escapeHtml(d.printed_at || 'gerade eben') + '</span>' +
            '<span class="mono-sm text-muted" style="margin-left:0.25rem;">' + escapeHtml(d.printer) + '</span>';
    }
});

es.addEventListener('fax_archived', function(e) {
    var d = JSON.parse(e.data);
    var card = document.querySelector('.fax-card-row[data-fax-id="' + d.fax_id + '"]');
    if (card && location.pathname !== '/archiv') card.remove();
});

es.addEventListener('fax_unarchived', function(e) {
    var d = JSON.parse(e.data);
    var card = document.querySelector('[data-fax-id="' + d.fax_id + '"]');
    if (card && location.pathname === '/archiv') card.remove();
});

// --- Status Buttons ---
function setStatus(faxId, status) {
    // Auto-Read-Timer abbrechen wenn User manuell Status setzt
    if (_autoReadTimer) {
        clearTimeout(_autoReadTimer);
        _autoReadTimer = null;
    }
    fetch('/api/fax/' + faxId + '/status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: status})
    }).catch(function() { showToast('Fehler', 'Status konnte nicht geaendert werden'); });
    // Sofort visuell aktualisieren
    document.querySelectorAll('.status-btns[data-fax-id="' + faxId + '"]').forEach(function(container) {
        container.querySelectorAll('.status-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.status === status);
        });
    });
}

// --- Category Change (detail view select) ---
document.addEventListener('change', function(e) {
    if (e.target.id === 'category-select') {
        var faxId = e.target.dataset.faxId;
        fetch('/api/fax/' + faxId + '/kategorie', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({category: e.target.value})
        }).catch(function() { showToast('Fehler', 'Kategorie konnte nicht geaendert werden'); });
    }
});

// --- Auto-Read after 5 seconds ---
var _autoReadTimer = null;
(function() {
    var faxIdEl = document.querySelector('[data-auto-read]');
    if (!faxIdEl) return;
    var faxId = faxIdEl.dataset.autoRead;
    var currentStatus = faxIdEl.dataset.currentStatus;
    if (currentStatus !== 'neu') return;
    _autoReadTimer = setTimeout(function() {
        _autoReadTimer = null;
        setStatus(parseInt(faxId), 'gelesen');
    }, 5000);
})();

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
        }).catch(function() { showToast('Fehler', 'Notiz konnte nicht gespeichert werden'); });
        form.querySelector('[name=message]').value = '';
    }
});

// --- Default Printer Cache ---
var _defaultPrinter = null;
fetch('/api/einstellungen/standarddrucker').then(function(r) { return r.json(); }).then(function(d) {
    _defaultPrinter = d.printer || null;
}).catch(function() {});

// --- Print ---
function printFax(faxId) {
    fetch('/api/drucker').then(function(r) { return r.json(); }).then(function(printers) {
        var names = Object.keys(printers);
        if (names.length === 0) { showToast('Fehler', 'Keine Drucker gefunden'); return; }
        var printer;
        if (_defaultPrinter && names.indexOf(_defaultPrinter) !== -1) {
            printer = _defaultPrinter;
        } else if (names.length === 1) {
            printer = names[0];
        } else {
            printer = prompt('Drucker waehlen:\n' + names.join('\n'));
        }
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

function quickPrint(faxId) { printFax(faxId); }

// --- Archive ---
function archiveFax(faxId) {
    if (!confirm('Fax wirklich archivieren?')) return;
    fetch('/api/fax/' + faxId + '/archivieren', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    }).then(function(r) { return r.json(); }).then(function(d) {
        if (d.ok) {
            showToast('Archiviert', 'Fax wurde ins Archiv verschoben');
            if (location.pathname.match(/^\/faxe\/\d+$/)) {
                location.href = '/faxe';
                return;
            }
            var card = document.querySelector('.fax-card-row[data-fax-id="' + faxId + '"]');
            if (card) card.remove();
        } else {
            showToast('Fehler', d.error || 'Archivierung fehlgeschlagen');
        }
    });
}

function unarchiveFax(faxId) {
    fetch('/api/fax/' + faxId + '/wiederherstellen', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    }).then(function(r) { return r.json(); }).then(function(d) {
        if (d.ok) {
            showToast('Wiederhergestellt', 'Fax zurueck in der Faxliste');
            var card = document.querySelector('[data-fax-id="' + faxId + '"]');
            if (card) card.remove();
        }
    });
}

// --- Address Book ---
function toggleAddressForm() {
    var c = document.getElementById('address-form-container');
    var show = c.style.display === 'none';
    c.style.display = show ? 'block' : 'none';
    if (!show && typeof resetAddressForm === 'function') resetAddressForm();
}

function saveAddress(e) {
    e.preventDefault();
    var form = e.target;
    var autoPrintEl = form.querySelector('[name=auto_print]');
    var printerEl = form.querySelector('[name=printer_name]');
    var copiesEl = form.querySelector('[name=print_copies]');
    var data = {
        phone_number: form.querySelector('[name=phone_number]').value.trim(),
        name: form.querySelector('[name=name]').value.trim(),
        default_category: form.querySelector('[name=default_category]').value,
        notes: form.querySelector('[name=notes]').value.trim(),
        auto_print: autoPrintEl ? autoPrintEl.checked : false,
        printer_name: printerEl ? printerEl.value : '',
        print_copies: copiesEl ? parseInt(copiesEl.value) || 1 : 1
    };
    fetch('/api/adressbuch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(function(r) { return r.json(); }).then(function(d) {
        if (d.ok) location.reload();
        else showToast('Fehler', d.error || 'Eintrag konnte nicht gespeichert werden');
    }).catch(function() { showToast('Fehler', 'Verbindungsfehler'); });
}

function deleteAddress(id) {
    if (!confirm('Eintrag wirklich loeschen?')) return;
    fetch('/api/adressbuch/' + id, {method: 'DELETE'}).then(function() { location.reload(); }).catch(function() { showToast('Fehler', 'Eintrag konnte nicht geloescht werden'); });
}

// --- Notifications ---
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}

function showBrowserNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {body: body});
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
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
