/* ──────────────────────────────────────────────────────────────────
   Patient feedback kiosk script. The pages work without it; it only makes them smoother.

   The questionnaire is one server-rendered form holding every step and
   every language, with the current step marked by the server. Without
   this file every step button posts the form and the server shows the
   next step (steps.py). With it:
     · the same steps (identify → the form's steps in number order, a
       screen of questions or a card per rating → review), switched in the
       page without reloading; the form controls are the only state and
       the page is posted once, from the review
     · the UHID cells, on-screen keypad and QR scanning (camera via
       BarcodeDetector, or a keyboard-mode USB/Bluetooth scanner)
     · questions shown only to guests or only to identified patients
     · instant language switching
     · an idle timer that starts over for the next patient
     · the browser's "Leave site?" question before a reload drops the answers
     · Home and Reset ask first before clearing answers
     · a Back button that never brings back a previous patient's page
     · typed text without the characters text_rules.py blocks (< > …)
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

  /* ── Leaving the page ────────────────────────────────────────── */
  // The kiosk's own ways out (submitting, Home and the other links, the
  // idle reset) leave without the browser's "Leave site?" question; see
  // "Leaving with answers" below.
  var leavingOnPurpose = false;
  function leaveTo(url) {
    leavingOnPurpose = true;
    window.location.replace(url);
  }
  // A click on a link that the page doesn't handle itself (the language
  // toggle and Reset do) navigates: Home, Back to the chooser, Start new.
  document.addEventListener('click', function (event) {
    if (!event.defaultPrevented && closest(event.target, 'a[href]')) leavingOnPurpose = true;
  });

  /* ── Back button ─────────────────────────────────────────────── */
  // The screen is shared, so the browser's history must not bring back a
  // previous patient's page. A page restored by Back (from the browser's
  // back/forward cache) starts over for the next patient.
  window.addEventListener('pageshow', function (event) {
    var start = body.getAttribute('data-home-url');
    if (event.persisted && start) leaveTo(start);
  });
  // Links marked data-replace (the thank-you page's "Start new") replace
  // the page in the history, so Back can't return to it. Its timed return
  // (meta refresh) replaces the page too.
  each(document.querySelectorAll('a[data-replace]'), function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      leaveTo(link.href);
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
        leaveTo(homeUrl);
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
  // The screens of the form's steps (steps/screen.html): "screen-<step>".
  var screens = form.querySelectorAll('[data-step^="screen-"]');

  // A step after identification: a screen of questions, a rating card or the review.
  function isFlow(name) {
    return name === 'questions' || name === 'review' || /^screen-/.test(name || '');
  }

  // Home / Reset show from the first rating on: on the cards, the review and
  // the screens after the ratings (data-home-reset).
  function showsHomeReset(name) {
    return name === 'questions' || name === 'review' || !!(steps[name] && steps[name].hasAttribute('data-home-reset'));
  }

  // The step buttons are submit buttons for the page without JavaScript;
  // here they move in the page instead (only the final Submit posts).
  var stepField = $('fStep');
  var cardField = $('fCard');
  var returnField = $('fReturn');
  if (uhidInput.hasAttribute('data-keypad')) uhidInput.setAttribute('inputmode', 'none');

  var current = null;       // name of the visible step
  var currentCard = 0;      // index into cards
  var identified = digitsOf(uhidInput.value).length === uhidLength;
  // Where Next leads back to: ['review', 0] after an answer opened from the
  // review, or the place the patient left to change their UHID (steps.py: return_to).
  var returnTo = null;
  var resumeAt = null;  // the place the patient left to change their UHID or switch to guest
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

  // A place's position in the whole questionnaire, whoever the patient is:
  // its step (data-order), then its card. Mirrors steps._rank.
  function rank(unit) {
    if (unit[0] === 'review') return 1e9;
    if (unit[0] === 'questions') {
      var card = cards[unit[1]];
      return (card ? parseInt(card.getAttribute('data-order'), 10) : 0) * 1000 + 1 + unit[1];
    }
    return (parseInt(unit[0].slice(7), 10) || 0) * 1000;
  }

  // The first step (or rating card), before ``before`` if given, that still needs an answer.
  function firstIncomplete(before) {
    var units = flow();
    for (var i = 0; i < units.length; i++) {
      if (before && rank(units[i]) >= rank(before)) break;
      var name = units[i][0];
      if (name === 'questions' ? !hasAnswer(cards[units[i][1]]) : name !== 'review' && !stepComplete(steps[name])) {
        return units[i];
      }
    }
    return null;
  }

  /* Moving between steps */
  function flow() {
    // The places after identification, in step order, for progress and
    // back/next: each screen with a question for this patient, each of
    // their rating cards, then the review. Mirrors steps.flow_units.
    var units = [];
    each(screens, function (screen) {
      if (hasVisibleQuestions(screen)) units.push([screen.getAttribute('data-step'), 0]);
    });
    each(cards, function (card, i) { if (!card.hidden) units.push(['questions', i]); });
    units.sort(function (a, b) { return rank(a) - rank(b); });
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
    // Back to the review after an edit (or to where the patient was before
    // changing their UHID), via anything that still needs an answer.
    if (returnTo) toward(returnTo);
    else goTo(flow()[position() + 1]);
  }

  // Goes back to ``target``: first to any place before it that needs an answer
  // (which then leads on to it), else straight there. A target no longer asked
  // (a question for identified patients only, after switching to guest) becomes
  // the place after it. Mirrors steps.toward.
  function toward(target) {
    var units = flow();
    var place = units[units.length - 1];
    for (var i = 0; i < units.length; i++) {
      if (rank(units[i]) >= rank(target)) { place = units[i]; break; }
    }
    var gap = firstIncomplete(place);
    returnTo = gap ? place : null;
    goTo(gap || place);
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
    // Leaving a question or the review to identify again (the UHID strip, or
    // Back to the first step): come back to that place after, answers kept.
    if ((name === 'identify' || name === 'uhid' || name === 'scan') && isFlow(current)) {
      resumeAt = current === 'review' ? ['review', 0] : returnTo || [current, currentCard];
      returnTo = null;
    }
    // The server's error / "too many" banner is about the page as it loaded.
    if (started) each(form.querySelectorAll('.banner'), function (banner) { banner.hidden = true; });
    current = name;
    if (stepField) stepField.value = name;
    for (var key in steps) {
      if (steps.hasOwnProperty(key)) steps[key].classList.toggle('is-active', key === name);
    }

    if (name === 'questions') {
      currentCard = cardIndex || 0;
      if (cardField) cardField.value = currentCard;
      each(cards, function (card, i) {
        card.classList.toggle('is-active', i === currentCard);
        card.setAttribute('aria-hidden', i === currentCard ? 'false' : 'true');
      });
      restartAnimation(cards[currentCard] && cards[currentCard].querySelector('.qhead'));
      updateNextButton(cards[currentCard]);
    }
    if (name === 'review') {
      returnTo = null;
      buildReview();
    }
    if (name === 'uhid') paintUhid();
    if (name === 'scan') startScan();

    var inFlow = name !== 'identify' && name !== 'scan' && name !== 'uhid';
    if (headerNav) headerNav.hidden = !showsHomeReset(name);
    if (idStrip) {
      idStrip.hidden = !(inFlow && identified);
      $('idStripValue').textContent = formatUhid(digitsOf(uhidInput.value));
    }
    if (progressFill) {
      var units = flow();
      progressFill.style.width = inFlow ? Math.round((position() + 1) / (units.length + 1) * 100) + '%' : '0%';
    }
    // An answer opened from the review returns to it: its step shows no Back (kiosk.css).
    form.classList.toggle('is-editing', !!returnTo && returnTo[0] === 'review');
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
    if (resumeAt) {
      // Back to where the patient was, every answer kept, via any question
      // that now needs an answer (e.g. age and sex after switching to guest).
      var target = resumeAt;
      resumeAt = null;
      toward(target);
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
  // In camera mode "Scan the QR" is offered only while scanning can work:
  // the browser reads QR codes, a camera is connected and camera permission
  // isn't denied. A scan that fails (permission refused, no camera) hides it
  // as well and sends the patient to typing the UHID. Each check updates
  // when its answer changes (permission changed, camera plugged in).
  var scanOption = form.querySelector('.opt[data-go="scan"]');
  var cameraBlocked = {};  // reason → true

  function blockCamera(reason, blocked) {
    cameraBlocked[reason] = blocked !== false;
    if (!scanOption) return;
    var hide = false;
    for (var key in cameraBlocked) {
      if (cameraBlocked.hasOwnProperty(key) && cameraBlocked[key]) hide = true;
    }
    scanOption.hidden = hide;
  }

  function checkCamera() {
    if (scanMode !== 'camera' || !scanOption) return;
    var media = navigator.mediaDevices;
    if (!window.BarcodeDetector || !media || !media.getUserMedia) {
      blockCamera('support');
      return;
    }
    try {
      if (window.BarcodeDetector.getSupportedFormats) {
        window.BarcodeDetector.getSupportedFormats().then(function (formats) {
          blockCamera('support', formats.indexOf('qr_code') < 0);
        }, function () {});
      }
    } catch (e) { /* assume QR codes are supported */ }
    var checkDevices = function () {
      if (!media.enumerateDevices) return;
      media.enumerateDevices().then(function (devices) {
        var found = false;
        each(devices, function (device) { if (device.kind === 'videoinput') found = true; });
        blockCamera('device', !found);
      }, function () {});
    };
    checkDevices();
    if (media.addEventListener) media.addEventListener('devicechange', checkDevices);
    try {
      if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({ name: 'camera' }).then(function (status) {
          var apply = function () { blockCamera('permission', status.state === 'denied'); };
          apply();
          status.onchange = apply;
        }, function () {});
      }
    } catch (e) { /* this browser can't report camera permission */ }
  }

  function scanned(raw) {
    if (continueWithUhid(raw)) return;
    // A keyboard scanner read something that isn't a UHID. Show the scan
    // step's message, unless the camera can't be used: then the UHID step.
    if (scanOption && scanOption.hidden) {
      show('uhid');
      $('uhidErr').hidden = false;
      return;
    }
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
    var detector = null;
    var busy = false;
    var unavailable = function (error) {
      stopCamera();
      var name = error && error.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') blockCamera('permission');
      else if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'NotReadableError') {
        blockCamera('device');
      } else blockCamera('support');
      // Scanning can't work here: let the patient type the UHID instead.
      if (current === 'scan') show('uhid');
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

  /* ── Typed text ──────────────────────────────────────────────── */
  // Characters used to write markup or code (< > { } ` \, text_rules.py)
  // can't be typed; the server refuses them too. They are dropped as they
  // are typed or pasted, and the question says why for a few seconds.
  var blocked = form.getAttribute('data-blocked-characters') || '';
  var blockedTimers = {};

  function withoutBlocked(text) {
    var kept = '';
    for (var i = 0; i < text.length; i++) {
      if (blocked.indexOf(text.charAt(i)) === -1) kept += text.charAt(i);
    }
    return kept;
  }

  function sayBlocked(question) {
    var message = question && question.querySelector('[data-error-characters]');
    if (!message) return;
    var key = question.getAttribute('data-question-key');
    message.hidden = false;
    clearTimeout(blockedTimers[key]);
    blockedTimers[key] = setTimeout(function () { message.hidden = true; }, 6000);
  }

  function dropBlocked(field) {
    var cleaned = withoutBlocked(field.value);
    if (cleaned === field.value) return;
    var caret = withoutBlocked(field.value.slice(0, field.selectionStart || 0)).length;
    field.value = cleaned;
    try { field.setSelectionRange(caret, caret); } catch (e) { /* not focused */ }
    sayBlocked(closest(field, '[data-question-key]'));
  }

  if (blocked) {
    form.addEventListener('input', function (event) {
      // Wait for an input method (e.g. a Kannada keyboard) to finish a character.
      if (event.target.tagName === 'TEXTAREA' && !event.isComposing) dropBlocked(event.target);
    });
    form.addEventListener('compositionend', function (event) {
      if (event.target.tagName === 'TEXTAREA') dropBlocked(event.target);
    });
    // Text sent back by the server after a refused submit.
    each(form.querySelectorAll('textarea'), dropBlocked);
  }

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

  // One row per question asked, in the order the patient met them.
  function reviewQuestions() {
    var out = [];
    each(flow(), function (unit) {
      if (unit[0] === 'questions') out.push(cards[unit[1]]);
      else if (unit[0] !== 'review') each(visible(steps[unit[0]].querySelectorAll('[data-question-key]')), function (q) { out.push(q); });
    });
    return out;
  }

  function buildReview() {
    var rows = $('reviewRows');
    var notAnswered = $('notAnsweredText').innerHTML;
    rows.innerHTML = '';
    each(reviewQuestions(), function (question) {
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
        returnTo = ['review', 0];
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
    // Step buttons post the page only without JavaScript; Submit still posts.
    var navButton = closest(event.target, 'button[name="nav"]');
    if (navButton && navButton.value !== 'submit') event.preventDefault();
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
      case 'screen-next': if (checkRequired(steps[current])) next(); break;
      case 'screen-back':
      case 'review-back': back(); break;
    }
  });

  // What Reset clears: the rating cards and the screens after the ratings
  // (those that show Home / Reset). The UHID (or guest choice) and the
  // screens before the ratings ("A few details") are kept.
  function resetSteps() {
    var out = [steps.questions];
    each(screens, function (screen) { if (screen.hasAttribute('data-home-reset')) out.push(screen); });
    return out;
  }

  // Reset (header): clear those answers and start again at the first of them.
  // Without JavaScript the link reloads the form, which clears everything.
  function resetAnswers() {
    each(resetSteps(), function (step) {
      if (!step) return;
      each(step.querySelectorAll('input, textarea'), function (control) {
        if (control.type === 'radio' || control.type === 'checkbox') control.checked = false;
        else control.value = '';
      });
      each(step.querySelectorAll('[data-error], [data-error-characters]'), function (error) { error.hidden = true; });
      each(step.querySelectorAll('.has-error'), function (question) { question.classList.remove('has-error'); });
    });
    each(form.querySelectorAll('.banner'), function (banner) { banner.hidden = true; });
    each(cards, updateNextButton);
    returnTo = null;
    resumeAt = null;
    var units = flow();
    for (var i = 0; i < units.length; i++) {
      if (showsHomeReset(units[i][0])) { goTo(units[i]); return; }
    }
  }

  /* ── Home and Reset ask first ────────────────────────────────── */
  // Home drops everything entered; Reset the ratings and open answers. Once
  // that would lose something, a card asks first, with "No, keep my answers"
  // as the default. The card is part of the page (not a browser pop-up, which
  // would freeze it), so the idle reset still clears the screen if the
  // patient walks away from it.
  var keepAnswers = null;  // closes the open card, if any

  function askFirst(card, opener, yes) {
    if (!card) { yes(); return; }
    var keepButton = card.querySelector('[data-confirm-keep]');
    var close = function () {
      card.hidden = true;
      keepAnswers = null;
    };
    keepButton.onclick = function () {
      close();
      if (opener && opener.focus) opener.focus();
    };
    card.querySelector('[data-confirm-yes]').onclick = function () {
      close();
      yes();
    };
    card.hidden = false;
    keepAnswers = keepButton.onclick;
    keepButton.focus();
  }

  // Escape (a keyboard, or a remote's Back key that sends it) keeps the answers.
  document.addEventListener('keydown', function (event) {
    if (keepAnswers && (event.key === 'Escape' || event.keyCode === 27)) keepAnswers();
  });

  // Anything Reset would clear: a rating, or an answer after the ratings.
  function answersToClear() {
    var found = false;
    each(resetSteps(), function (step) {
      if (!step || found) return;
      if (step.querySelector('input[type=radio]:checked')) found = true;
      each(step.querySelectorAll('textarea'), function (field) {
        if (String(field.value).replace(/\s+/g, '') !== '') found = true;
      });
    });
    return found;
  }

  var homeLink = headerNav && headerNav.querySelector('.navbtn--home');
  if (homeLink) {
    homeLink.addEventListener('click', function (event) {
      if (!anythingEntered()) return; // nothing to lose: just go
      event.preventDefault();
      askFirst($('confirmHome'), homeLink, function () {
        leavingOnPurpose = true; // no "Leave site?" on top
        window.location.href = homeLink.getAttribute('href');
      });
    });
  }

  var resetLink = headerNav && headerNav.querySelector('[data-action="reset"]');
  if (resetLink) {
    resetLink.addEventListener('click', function (event) {
      event.preventDefault();
      if (answersToClear()) askFirst($('confirmReset'), resetLink, resetAnswers);
      else resetAnswers();
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
    if (returnField) returnField.value = '';
    submitting = true;
    leavingOnPurpose = true;
  });

  /* ── Leaving with answers ────────────────────────────────────── */
  // Reloading or closing the page drops what was entered (a pull-down while
  // scrolling on a tablet reloads it too). Once anything is entered, the
  // browser asks first with its own "Leave site?" / "Reload site?" question;
  // browsers word it themselves and don't show page text. The kiosk's own
  // ways out don't ask (see "Leaving the page"), so the idle reset is never
  // held up by the question.
  function anythingEntered() {
    if (form.querySelector('input[type=radio]:checked')) return true;
    var fields = form.querySelectorAll('textarea, input[type=date], #uhidInput');
    for (var i = 0; i < fields.length; i++) {
      if (String(fields[i].value).replace(/\s+/g, '') !== '') return true;
    }
    return false;
  }

  window.addEventListener('beforeunload', function (event) {
    if (leavingOnPurpose || !anythingEntered()) return undefined;
    event.preventDefault();
    event.returnValue = ''; // older browsers ask only when this is set
    return '';
  });

  /* ── Start ───────────────────────────────────────────────────── */
  checkCamera();
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
