/* ──────────────────────────────────────────────────────────────────
   Patient feedback kiosk — progressive enhancement only.

   The questionnaire is one server-rendered form holding every step and
   every language. Without this file it is one long form. With it:
     · one step at a time (identify → details → one card per rating →
       open questions → review), switched in the page; the form controls
       are the only state and the page is posted once, from the review
     · the UHID cells, on-screen keypad and QR scanning (camera via
       BarcodeDetector, or a keyboard-mode USB/Bluetooth scanner)
     · questions shown only to guests or only to identified patients
     · instant language switching
     · an idle timer that starts over for the next patient
   Plain ES5 so it runs on older TV browsers.
   ────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var root = document.documentElement;
  var body = document.body;
  function $(id) { return document.getElementById(id); }
  function each(list, fn) { for (var i = 0; i < list.length; i++) fn(list[i], i); }
  function digitsOf(value) { return String(value || '').replace(/\D/g, ''); }
  function closest(element, selector) {
    while (element && element.nodeType === 1) {
      if (matches(element, selector)) return element;
      element = element.parentNode;
    }
    return null;
  }
  function matches(element, selector) {
    var fn = element.matches || element.msMatchesSelector || element.webkitMatchesSelector;
    return fn.call(element, selector);
  }

  /* ── Language ────────────────────────────────────────────────── */
  // Every string is already in the page; CSS shows the current language.
  // Attributes (placeholders, aria-labels) carry data-l10n-<attr> JSON.
  var localized = [];
  each(document.getElementsByTagName('*'), function (element) {
    each(element.attributes, function (attribute) {
      if (attribute.name.indexOf('data-l10n-') !== 0) return;
      try {
        localized.push([element, attribute.name.slice(10), JSON.parse(attribute.value)]);
      } catch (e) { /* ignore a malformed value */ }
    });
  });

  function setLanguage(code) {
    root.setAttribute('data-lang', code);
    root.setAttribute('lang', code);
    each(localized, function (item) {
      if (item[2][code] !== undefined) item[0].setAttribute(item[1], item[2][code]);
    });
    each(document.querySelectorAll('[data-set-lang]'), function (link) {
      var on = link.getAttribute('data-set-lang') === code;
      link.classList.toggle('is-on', on);
      if (on) link.setAttribute('aria-current', 'true'); else link.removeAttribute('aria-current');
    });
    var field = $('fLang');
    if (field) field.value = code;
    // Links within the patient's visit (form choice, Back, Home, Reset) keep it.
    each(document.querySelectorAll('a[data-carry-lang]'), function (link) {
      link.setAttribute('href', withLanguage(link.getAttribute('href'), code));
    });
  }

  // ``href`` with its ?language= set to ``code`` (other parameters kept).
  function withLanguage(href, code) {
    var hash = '';
    var at = href.indexOf('#');
    if (at > -1) { hash = href.slice(at); href = href.slice(0, at); }
    var parts = href.split('?');
    var params = (parts[1] || '').split('&').filter(function (param) {
      return param && param.indexOf('language=') !== 0;
    });
    params.push('language=' + encodeURIComponent(code));
    return parts[0] + '?' + params.join('&') + hash;
  }

  each(document.querySelectorAll('[data-set-lang]'), function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      setLanguage(link.getAttribute('data-set-lang'));
    });
  });

  /* ── Idle reset ──────────────────────────────────────────────── */
  // Once someone has touched the screen, a quiet spell sends the kiosk
  // back to the start, dropping anything entered.
  var idleSeconds = parseInt(body.getAttribute('data-idle-timeout'), 10) || 0;
  if (idleSeconds > 0) {
    var homeUrl = body.getAttribute('data-home-url');
    var overlay = $('idleOverlay');
    var overlayText = $('idleBody');
    var warnSeconds = Math.min(15, Math.floor(idleSeconds / 3));
    // Armed from the start when the page holds a patient's choices (their
    // answers after a failed submit, their language); otherwise on first touch.
    var lastActivity = body.getAttribute('data-idle-armed') === '1' ? Date.now() : 0;
    var leaving = false;

    var activity = function () {
      lastActivity = Date.now();
      if (overlay && !overlay.hidden) overlay.hidden = true;
    };
    each(['pointerdown', 'touchstart', 'mousedown', 'keydown', 'input', 'wheel'], function (name) {
      document.addEventListener(name, activity, true);
    });

    setInterval(function () {
      if (leaving || !lastActivity) return;
      var left = Math.ceil(idleSeconds - (Date.now() - lastActivity) / 1000);
      if (left <= 0) {
        leaving = true;
        window.location.replace(homeUrl);
      } else if (left <= warnSeconds && overlay) {
        overlayText.textContent = (overlayText.getAttribute('data-template') || '').replace('{n}', left);
        overlay.hidden = false;
      }
    }, 500);
  }

  /* ── The questionnaire ───────────────────────────────────────── */
  var form = $('feedback');
  if (!form) return;

  var uhidInput = $('uhidInput');
  var uhidLength = parseInt(form.getAttribute('data-uhid-length'), 10) || 11;
  var scanMode = form.getAttribute('data-scan-mode');
  var steps = {};
  each(form.querySelectorAll('[data-step]'), function (step) { steps[step.getAttribute('data-step')] = step; });
  var cards = steps.questions ? steps.questions.querySelectorAll('[data-card]') : [];
  var progressFill = $('progressFill');
  var headerNav = $('hdrNav');
  var idStrip = $('idStrip');
  // Home / Reset show from the first rating question on, in every flow.
  var NAV_STEPS = ['questions', 'comments', 'review'];

  var current = null;       // name of the visible step
  var currentCard = 0;      // index into cards
  var identified = digitsOf(uhidInput.value).length === uhidLength;
  var returnToReview = false;  // an edit from the review goes back to it
  var resumeAtReview = false;  // left the review to change the UHID: come back to it
  var started = false;
  var submitting = false;
  var advanceTimer = null;

  /* Questions for guests only / identified patients only */
  function isShownTo(element) {
    var audience = element.getAttribute('data-audience');
    return audience === 'guest' ? !identified : audience === 'identified' ? identified : true;
  }

  function applyAudience() {
    each(form.querySelectorAll('[data-audience]'), function (element) {
      var shown = isShownTo(element);
      element.hidden = !shown;
      // Hidden questions are not posted.
      each(element.querySelectorAll('input, textarea, select'), function (control) { control.disabled = !shown; });
    });
    renumberCards();
  }

  function visible(list) {
    var out = [];
    each(list, function (element) { if (!element.hidden) out.push(element); });
    return out;
  }

  function visibleCards() { return visible(cards); }

  function hasVisibleQuestions(step) {
    return !!step && visible(step.querySelectorAll('[data-question-key]')).length > 0;
  }

  function renumberCards() {
    var template = $('counterTemplate');
    if (!template) return;
    var shown = visibleCards();
    each(shown, function (card, i) {
      var badge = card.querySelector('[data-counter]');
      if (badge) badge.innerHTML = template.innerHTML.replace(/\{n\}/g, i + 1).replace(/\{total\}/g, shown.length);
    });
  }

  /* Answers */
  function hasAnswer(question) {
    var controls = question.querySelectorAll('input, textarea, select');
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i];
      if (control.hasAttribute('data-comment')) continue;
      if (control.type === 'radio' || control.type === 'checkbox') {
        if (control.checked) return true;
      } else if (String(control.value).replace(/\s+/g, '') !== '') {
        return true;
      }
    }
    return false;
  }

  function showError(question, on) {
    var error = question.querySelector('[data-error]');
    if (error) error.hidden = !on;
    var dateError = question.querySelector('[data-error-date]');
    if (dateError && !on) dateError.hidden = true;
    question.classList.toggle('has-error', !!on);
  }

  function isMissing(question) {
    return question.getAttribute('data-required') === '1' && !hasAnswer(question);
  }

  // A date after its max (today), which the server would refuse.
  function hasFutureDate(question) {
    var input = question.querySelector('input[type=date]');
    return !!(input && input.value && input.max && input.value > input.max);
  }

  // Shows the error under each required question left empty (or given a
  // future date); true if none.
  function checkRequired(step) {
    var first = null;
    each(visible(step.querySelectorAll('[data-question-key]')), function (question) {
      var missing = isMissing(question);
      var future = !missing && hasFutureDate(question);
      showError(question, missing);
      var dateError = question.querySelector('[data-error-date]');
      if (dateError) dateError.hidden = !future;
      if (future) question.classList.add('has-error');
      if ((missing || future) && !first) first = question;
    });
    if (first && first.scrollIntoView) first.scrollIntoView({ block: 'center' });
    return !first;
  }

  function stepComplete(step) {
    var questions = visible(step.querySelectorAll('[data-question-key]'));
    for (var i = 0; i < questions.length; i++) {
      if (isMissing(questions[i]) || hasFutureDate(questions[i])) return false;
    }
    return true;
  }

  // The first step (or rating card) that still needs an answer, if any.
  function firstIncomplete() {
    var units = flow();
    for (var i = 0; i < units.length; i++) {
      var name = units[i][0];
      if (name === 'questions' ? !hasAnswer(cards[units[i][1]]) : name !== 'review' && !stepComplete(steps[name])) {
        return units[i];
      }
    }
    return null;
  }

  /* Moving between steps */
  function flow() {
    // The steps after identification, in order, for progress and back/next.
    var units = [];
    if (hasVisibleQuestions(steps.details)) units.push(['details', 0]);
    each(cards, function (card, i) { if (!card.hidden) units.push(['questions', i]); });
    if (hasVisibleQuestions(steps.comments)) units.push(['comments', 0]);
    units.push(['review', 0]);
    return units;
  }

  function position() {
    var units = flow();
    for (var i = 0; i < units.length; i++) {
      if (units[i][0] === current && (current !== 'questions' || units[i][1] === currentCard)) return i;
    }
    return -1;
  }

  function goTo(unit) {
    if (unit) show(unit[0], unit[1]);
  }

  function next() {
    // Back to the review after an edit, via anything that still needs an answer.
    if (returnToReview) goTo(firstIncomplete() || ['review', 0]);
    else goTo(flow()[position() + 1]);
  }

  function back() {
    var index = position();
    if (index <= 0) show('identify'); else goTo(flow()[index - 1]);
  }

  function restartAnimation(element) {
    if (!element) return;
    element.style.animation = 'none';
    void element.offsetWidth; // reflow so the entrance animation plays again
    element.style.animation = '';
  }

  function show(name, cardIndex) {
    if (!steps[name]) return;
    if (advanceTimer) { clearTimeout(advanceTimer); advanceTimer = null; }
    if (current === 'scan' && name !== 'scan') stopCamera();
    // Leaving the review (or an edit from it) to identify again: come back to it after.
    if ((name === 'identify' || name === 'uhid' || name === 'scan') && (current === 'review' || returnToReview)) {
      resumeAtReview = true;
      returnToReview = false;
    }
    // The server's error / "too many" banner is about the page as it loaded.
    if (started) each(form.querySelectorAll('.banner'), function (banner) { banner.hidden = true; });
    current = name;
    for (var key in steps) {
      if (steps.hasOwnProperty(key)) steps[key].classList.toggle('is-active', key === name);
    }

    if (name === 'questions') {
      currentCard = cardIndex || 0;
      each(cards, function (card, i) {
        card.classList.toggle('is-active', i === currentCard);
        card.setAttribute('aria-hidden', i === currentCard ? 'false' : 'true');
      });
      restartAnimation(cards[currentCard] && cards[currentCard].querySelector('.qhead'));
      updateNextButton(cards[currentCard]);
    }
    if (name === 'review') {
      returnToReview = false;
      buildReview();
    }
    if (name === 'uhid') paintUhid();
    if (name === 'scan') startScan();

    var inFlow = name !== 'identify' && name !== 'scan' && name !== 'uhid';
    if (headerNav) headerNav.hidden = NAV_STEPS.indexOf(name) < 0;
    if (idStrip) {
      idStrip.hidden = !(inFlow && identified);
      $('idStripValue').textContent = formatUhid(digitsOf(uhidInput.value));
    }
    if (progressFill) {
      var units = flow();
      progressFill.style.width = inFlow ? Math.round((position() + 1) / (units.length + 1) * 100) + '%' : '0%';
    }
    window.scrollTo(0, 0);
    // Keep TV-remote focus inside the visible step.
    if (document.activeElement && document.activeElement !== body && (name !== 'questions' || cards[currentCard])) {
      var target = name === 'questions'
        ? cards[currentCard].querySelector('input:checked') || cards[currentCard].querySelector('input')
        : steps[name].querySelector('button, input:not([type=hidden]), textarea, a');
      if (target && target.focus) target.focus();
    }
  }

  // After the patient identified themselves (or chose not to).
  function startQuestions() {
    applyAudience();
    if (resumeAtReview) {
      // Back to the review, via any question that now needs an answer
      // (e.g. age and sex after switching to guest).
      resumeAtReview = false;
      returnToReview = true;
      goTo(firstIncomplete() || ['review', 0]);
    } else {
      goTo(flow()[0]);
    }
  }

  function continueAsGuest() {
    identified = false;
    uhidInput.value = '';
    paintUhid();
    startQuestions();
  }

  function continueWithUhid(raw) {
    var digits = digitsOf(raw);
    if (digits.length !== uhidLength) return false;
    uhidInput.value = digits;
    identified = true;
    hideUhidError();
    startQuestions();
    return true;
  }

  /* ── UHID entry ──────────────────────────────────────────────── */
  var uhidWrap = $('uhidWrap');
  var uhidCells = uhidWrap.querySelectorAll('.uhid-cell');
  var uhidGroups = [];
  each(uhidCells, function (cell, i) { if (i && cell.className.indexOf('uhid-cell--gap') > -1) uhidGroups.push(i); });

  function formatUhid(digits) {
    var out = '';
    for (var i = 0; i < digits.length; i++) {
      if (uhidGroups.indexOf(i) > -1) out += ' ';
      out += digits.charAt(i);
    }
    return out;
  }

  function hideUhidError() {
    $('uhidErr').hidden = true;
    uhidInput.removeAttribute('aria-invalid');
  }

  function paintUhid() {
    var digits = digitsOf(uhidInput.value).slice(0, uhidLength);
    if (uhidInput.value !== digits) uhidInput.value = digits;
    each(uhidCells, function (cell, i) {
      cell.textContent = i < digits.length ? digits.charAt(i) : '';
      cell.classList.toggle('is-filled', i < digits.length);
      cell.classList.toggle('is-active', i === digits.length || (digits.length === uhidLength && i === uhidLength - 1));
    });
  }

  function submitUhid() {
    if (continueWithUhid(uhidInput.value)) return;
    $('uhidErr').hidden = false;
    uhidInput.setAttribute('aria-invalid', 'true');
  }

  uhidInput.addEventListener('input', function () { hideUhidError(); paintUhid(); });
  uhidInput.addEventListener('focus', function () { uhidWrap.classList.add('is-focus'); });
  uhidInput.addEventListener('blur', function () { uhidWrap.classList.remove('is-focus'); });
  uhidWrap.addEventListener('click', function () { uhidInput.focus(); });

  each(form.querySelectorAll('[data-key]'), function (key) {
    key.addEventListener('click', function () {
      var digits = digitsOf(uhidInput.value);
      var value = key.getAttribute('data-key');
      if (value === 'back') digits = digits.slice(0, -1);
      else if (value === 'clear') digits = '';
      else digits = (digits + value).slice(0, uhidLength);
      uhidInput.value = digits;
      hideUhidError();
      paintUhid();
    });
  });

  /* ── QR scanning ─────────────────────────────────────────────── */
  function scanned(raw) {
    if (continueWithUhid(raw)) return;
    if (current !== 'scan') show('scan');
    var error = $('scanError');
    if (error) error.hidden = false;
  }

  // A keyboard-mode scanner "types" the code within a few milliseconds,
  // usually ending with Enter or Tab. People are much slower, and a TV
  // remote's OK button sends Enter with nothing buffered, so it is ignored.
  var buffer = '';
  var lastKeyAt = 0;
  var flushTimer = null;
  function flush() {
    flushTimer = null;
    var code = buffer;
    buffer = '';
    if (digitsOf(code).length >= 6) scanned(code);
  }
  document.addEventListener('keydown', function (event) {
    if (current !== 'identify' && current !== 'scan') return;
    var target = event.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
    var now = Date.now();
    if (now - lastKeyAt > 80) buffer = '';
    lastKeyAt = now;
    if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
    var key = event.key;
    if (key === 'Enter' || key === 'Tab') {
      if (digitsOf(buffer).length >= 6) { event.preventDefault(); flush(); }
      buffer = '';
    } else if (key && key.length === 1) {
      buffer += key;
      // Scanners that send no terminator: take the code once typing stops.
      if (digitsOf(buffer).length >= uhidLength) flushTimer = setTimeout(flush, 150);
    }
  });

  var video = $('camVideo');
  var stream = null;
  var scanTimer = null;

  function stopCamera() {
    if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
    if (stream) {
      each(stream.getTracks(), function (track) { track.stop(); });
      stream = null;
    }
    if (video) video.srcObject = null;
  }

  function startScan() {
    var error = $('scanError');
    if (error) error.hidden = true;
    if (scanMode !== 'camera' || stream) return;
    var callout = $('camCallout');
    var detector = null;
    var busy = false;
    var unavailable = function () {
      stopCamera();
      if (callout) callout.hidden = false;
    };
    try {
      detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    } catch (e) {
      detector = null;
    }
    if (!detector || !video || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      unavailable();
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
      .then(function (s) {
        if (current !== 'scan') { each(s.getTracks(), function (track) { track.stop(); }); return; }
        stream = s;
        video.srcObject = s;
        var playing = video.play();
        if (playing && playing.catch) playing.catch(function () {});
        scanTimer = setInterval(function () {
          if (busy || video.readyState < 2) return;
          busy = true;
          detector.detect(video).then(function (codes) {
            busy = false;
            for (var i = 0; i < codes.length; i++) {
              if (digitsOf(codes[i].rawValue).length === uhidLength) {
                stopCamera();
                scanned(codes[i].rawValue);
                return;
              }
            }
          }).catch(function () { busy = false; });
        }, 350);
      })
      .catch(unavailable);
  }
  window.addEventListener('pagehide', stopCamera);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopCamera();
    else if (current === 'scan') startScan();
  });

  /* ── Rating cards ────────────────────────────────────────────── */
  // A tap on a rating moves on by itself; arrow keys only change the
  // choice, so TV-remote users aren't rushed past a question.
  var pointerAt = 0;

  function updateNextButton(card) {
    if (!card) return;
    var nextButton = card.querySelector('[data-nav="next"]');
    if (nextButton) nextButton.classList.toggle('is-disabled', !hasAnswer(card));
  }

  function picked(card, advance) {
    showError(card, false);
    updateNextButton(card);
    if (!advance) return;
    if (advanceTimer) clearTimeout(advanceTimer);
    advanceTimer = setTimeout(function () { advanceTimer = null; next(); }, 300);
  }

  each(cards, function (card) {
    each(card.querySelectorAll('.rate-option'), function (option) {
      option.addEventListener('mousedown', function () { pointerAt = Date.now(); });
      option.addEventListener('touchstart', function () { pointerAt = Date.now(); });
    });
    each(card.querySelectorAll('input[type=radio]'), function (radio) {
      radio.addEventListener('change', function () { picked(card, Date.now() - pointerAt < 1500); });
      radio.addEventListener('click', function () {
        // Tapping the answer already chosen still moves on.
        if (radio.checked && Date.now() - pointerAt < 1500) picked(card, true);
      });
      radio.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.keyCode !== 13) return;
        event.preventDefault();
        radio.checked = true;
        picked(card, true);
      });
    });
    card.querySelector('[data-nav="next"]').addEventListener('click', function () {
      if (hasAnswer(card)) next(); else showError(card, true);
    });
    card.querySelector('[data-nav="back"]').addEventListener('click', back);
  });

  // Answering clears that question's error.
  form.addEventListener('change', function (event) {
    var question = closest(event.target, '[data-question-key]');
    if (question && hasAnswer(question)) showError(question, false);
  });
  form.addEventListener('input', function (event) {
    var question = closest(event.target, '[data-question-key]');
    if (question && hasAnswer(question)) showError(question, false);
  });

  /* ── Review ──────────────────────────────────────────────────── */
  function answerHtml(question) {
    var checked = question.querySelector('input[type=radio]:checked');
    if (checked) {
      var face = checked.nextElementSibling;
      var label = face && (face.querySelector('.rate-label') || face);
      return label ? label.innerHTML : '';
    }
    var date = question.querySelector('input[type=date]');
    if (date) {
      var parts = date.value.split('-');
      return parts.length === 3 ? escapeHtml(parts[2] + '/' + parts[1] + '/' + parts[0]) : '';
    }
    var text = question.querySelector('textarea');
    return text ? escapeHtml(text.value.replace(/^\s+|\s+$/g, '')) : '';
  }

  function commentText(question) {
    var comment = question.querySelector('[data-comment]');
    var value = comment ? comment.value.replace(/^\s+|\s+$/g, '') : '';
    if (value.length > 60) value = value.slice(0, 57) + '…';
    return value;
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function buildReview() {
    var rows = $('reviewRows');
    var notAnswered = $('notAnsweredText').innerHTML;
    rows.innerHTML = '';
    each(visible(form.querySelectorAll('[data-question-key]')), function (question) {
      var step = closest(question, '[data-step]');
      if (!step) return;
      var value = answerHtml(question);
      var comment = commentText(question);
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'row';
      row.innerHTML = '<span class="row-label">' + question.querySelector('.q-label').innerHTML + '</span>' +
        '<span class="row-value' + (value ? '' : ' is-empty') + '">' + (value || notAnswered) +
        (value && comment ? '<span class="row-note">' + escapeHtml(comment) + '</span>' : '') + '</span>';
      row.addEventListener('click', function () {
        returnToReview = true;
        var name = step.getAttribute('data-step');
        var index = 0;
        each(cards, function (card, i) { if (card === question) index = i; });
        show(name, index);
        if (name !== 'questions' && question.scrollIntoView) question.scrollIntoView({ block: 'center' });
      });
      rows.appendChild(row);
    });
  }

  /* ── Buttons ─────────────────────────────────────────────────── */
  form.addEventListener('click', function (event) {
    var button = closest(event.target, '[data-go], [data-action]');
    if (!button || !form.contains(button)) return;
    var go = button.getAttribute('data-go');
    if (go) {
      if (go === 'uhid' && current === 'scan') stopCamera();
      show(go);
      return;
    }
    switch (button.getAttribute('data-action')) {
      case 'guest': continueAsGuest(); break;
      case 'uhid-continue': submitUhid(); break;
      case 'details-next': if (checkRequired(steps.details)) next(); break;
      case 'comments-next': if (checkRequired(steps.comments)) next(); break;
      case 'comments-back':
      case 'review-back': back(); break;
    }
  });

  // Reset (header): clear the ratings and open answers and start again at the
  // first question. The UHID (or guest choice) and the details are kept.
  // Without JavaScript the link reloads the form, which clears everything.
  function resetAnswers() {
    each([steps.questions, steps.comments], function (step) {
      if (!step) return;
      each(step.querySelectorAll('input, textarea'), function (control) {
        if (control.type === 'radio' || control.type === 'checkbox') control.checked = false;
        else control.value = '';
      });
      each(step.querySelectorAll('[data-error]'), function (error) { error.hidden = true; });
      each(step.querySelectorAll('.has-error'), function (question) { question.classList.remove('has-error'); });
    });
    each(form.querySelectorAll('.banner'), function (banner) { banner.hidden = true; });
    each(cards, updateNextButton);
    returnToReview = false;
    resumeAtReview = false;
    var units = flow();
    for (var i = 0; i < units.length; i++) {
      if (units[i][0] !== 'details') { goTo(units[i]); return; }
    }
  }

  var resetLink = headerNav && headerNav.querySelector('[data-action="reset"]');
  if (resetLink) {
    resetLink.addEventListener('click', function (event) {
      event.preventDefault();
      resetAnswers();
    });
  }

  /* ── Submitting ──────────────────────────────────────────────── */
  // Enter must not post the form from a half-finished step.
  form.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.keyCode !== 13) return;
    var target = event.target;
    if (target.tagName === 'TEXTAREA' || target.tagName === 'BUTTON' || target.tagName === 'A') return;
    event.preventDefault();
    if (target === uhidInput) submitUhid();
    // A TV remote's OK button sends Enter: let it pick a choice.
    else if (target.type === 'radio' && !target.checked) {
      target.checked = true;
      var question = closest(target, '[data-question-key]');
      if (question) showError(question, false);
    }
  });

  form.addEventListener('submit', function (event) {
    if (current !== 'review' || submitting) { event.preventDefault(); return; }
    if (!identified) uhidInput.value = '';
    submitting = true;
  });

  // Pages restored from the back/forward cache must accept input again.
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) submitting = false;
  });

  /* ── Start ───────────────────────────────────────────────────── */
  applyAudience();
  paintUhid();
  each(cards, updateNextButton);
  var startStep = form.getAttribute('data-start-step') || 'identify';
  var startCard = parseInt(form.getAttribute('data-start-card'), 10) || 0;
  // After a failed submit some of the server's errors may be on questions
  // that no longer apply; start from the step it pointed at.
  show(steps[startStep] ? startStep : 'identify', startCard);
  started = true;
})();
