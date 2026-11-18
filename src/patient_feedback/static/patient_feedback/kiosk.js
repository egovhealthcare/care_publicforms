/* ──────────────────────────────────────────────────────────────────
   Patient feedback kiosk — progressive enhancement only.

   Every screen is server-rendered and works without this file. It adds:
     · an idle timer that returns the kiosk to the start screen
     · stepping through the rating questions on one page, with the
       answers saved in the background
     · the UHID cells + instant on-screen keypad
     · QR scanning with the camera (BarcodeDetector) or a keyboard-mode
       USB/Bluetooth scanner
     · language switching that keeps what was typed on form screens
   Plain ES5 so it runs on older TV browsers.
   ────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var body = document.body;
  function $(id) { return document.getElementById(id); }
  function each(list, fn) { for (var i = 0; i < list.length; i++) fn(list[i], i); }
  function digitsOf(value) { return String(value || '').replace(/\D/g, ''); }

  /* ── Forms: submit once ──────────────────────────────────────── */
  function claim(form) {
    if (form.getAttribute('data-submitting')) return false;
    form.setAttribute('data-submitting', '1');
    return true;
  }

  function submitWith(form, name, value) {
    if (!claim(form)) return;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.appendChild(input);
    form.submit();
  }

  document.addEventListener('submit', function (event) {
    if (!claim(event.target)) event.preventDefault();
  }, true);

  // Pages restored from the back/forward cache must accept input again.
  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) return;
    each(document.querySelectorAll('form[data-submitting]'), function (form) {
      form.removeAttribute('data-submitting');
    });
  });

  /* ── Language toggle on form screens keeps unsaved input ─────── */
  var screenForm = $('screen-form');
  if (screenForm) {
    each(document.querySelectorAll('a.langbtn[data-lang]'), function (link) {
      link.addEventListener('click', function (event) {
        event.preventDefault();
        if (link.className.indexOf('is-on') > -1) return;
        submitWith(screenForm, '_lang', link.getAttribute('data-lang'));
      });
    });
  }

  /* ── Rating questions: one page, one card at a time ─────────── */
  // The server renders every question and marks the current card. Here a
  // tap stores the answer in a hidden field, saves it in the background and
  // moves to the next card; the last answer submits the page.
  var questionsForm = document.querySelector('form[data-questions]');
  if (questionsForm) {
    var cards = questionsForm.querySelectorAll('.qcard');
    var total = cards.length;
    var current = parseInt(questionsForm.getAttribute('data-start'), 10) || 0;
    var backToReview = questionsForm.getAttribute('data-return') === 'review';
    var currentField = $('qCurrent');
    var progressFill = document.querySelector('.progress-fill');
    var progressBase = parseFloat(questionsForm.getAttribute('data-progress-base')) || 0;
    var progressTotal = parseFloat(questionsForm.getAttribute('data-progress-total')) || total;
    var advanceTimer = null;

    var valueField = function (index) { return $('qValue' + index); };

    var restartAnimation = function (element) {
      if (!element) return;
      element.style.animation = 'none';
      void element.offsetWidth; // reflow so the entrance animation plays again
      element.style.animation = '';
    };

    var show = function (index) {
      if (advanceTimer) { clearTimeout(advanceTimer); advanceTimer = null; }
      current = index;
      currentField.value = index;
      each(cards, function (card, i) {
        card.classList.toggle('is-active', i === index);
        card.setAttribute('aria-hidden', i === index ? 'false' : 'true');
      });
      if (progressFill) {
        progressFill.style.width = Math.round((progressBase + index + 1) / progressTotal * 100) + '%';
      }
      restartAnimation(cards[index].querySelector('.qhead'));
      window.scrollTo(0, 0);
      // Keep TV-remote focus on the visible card.
      var focusTarget = cards[index].querySelector('.rate.is-on') || cards[index].querySelector('.rate');
      if (focusTarget && document.activeElement && document.activeElement !== body) focusTarget.focus();
    };

    // Save answers as they are given, so nothing is lost if the patient
    // switches language or wanders off, and the server knows they're active.
    var autosave = function () {
      if (!window.fetch || !window.FormData) return;
      var data = new FormData(questionsForm);
      data.append('autosave', '1');
      try {
        window.fetch(questionsForm.getAttribute('action') || window.location.href, {
          method: 'POST', body: data, credentials: 'same-origin', keepalive: true
        }).catch(function () {});
      } catch (e) { /* old browser: the final submit still carries every answer */ }
    };

    var finish = function () { submitWith(questionsForm, 'action', 'done'); };
    var goNext = function () { if (current < total - 1) show(current + 1); else finish(); };

    each(cards, function (card, index) {
      var rateButtons = card.querySelectorAll('.rate');
      var nextButton = card.querySelector('[data-nav="next"]');
      var backButton = card.querySelector('[data-nav="back"]');

      each(rateButtons, function (button) {
        button.addEventListener('click', function (event) {
          event.preventDefault();
          if (questionsForm.getAttribute('data-submitting')) return;
          valueField(index).value = button.value.split(':')[1];
          each(rateButtons, function (other) {
            other.classList.remove('is-on');
            other.setAttribute('aria-pressed', 'false');
          });
          button.classList.add('is-on');
          button.setAttribute('aria-pressed', 'true');
          if (nextButton) nextButton.disabled = false;
          autosave();
          if (advanceTimer) clearTimeout(advanceTimer);
          advanceTimer = setTimeout(function () {
            advanceTimer = null;
            if (backToReview) finish(); else goNext();
          }, 300);
        });
      });

      if (nextButton) {
        nextButton.addEventListener('click', function (event) {
          event.preventDefault();
          if (valueField(index).value !== '') goNext();
        });
      }
      if (backButton) {
        backButton.addEventListener('click', function (event) {
          event.preventDefault();
          if (index > 0) show(index - 1);
          else submitWith(questionsForm, 'nav', 'back:0'); // saves answers, then leaves
        });
      }
    });

    // The header's Home button goes back to the first question in place.
    var homeLink = document.querySelector('.navbtn--home');
    if (homeLink) {
      homeLink.addEventListener('click', function (event) {
        event.preventDefault();
        show(0);
      });
    }
  }

  /* ── UHID entry ──────────────────────────────────────────────── */
  var uhidWrap = $('uhidWrap');
  if (uhidWrap) {
    var uhidInput = $('uhidInput');
    var uhidForm = uhidInput.form;
    var cells = uhidWrap.querySelectorAll('.uhid-cell');
    var maxDigits = cells.length;

    var hideError = function () {
      var error = $('uhidErr');
      if (error) error.style.display = 'none';
      uhidInput.removeAttribute('aria-invalid');
    };

    var paint = function () {
      var digits = digitsOf(uhidInput.value).slice(0, maxDigits);
      if (uhidInput.value !== digits) uhidInput.value = digits;
      each(cells, function (cell, i) {
        cell.textContent = i < digits.length ? digits.charAt(i) : '';
        cell.classList.toggle('is-filled', i < digits.length);
        cell.classList.toggle('is-active', i === digits.length || (digits.length === maxDigits && i === maxDigits - 1));
      });
    };

    uhidInput.addEventListener('input', function () { hideError(); paint(); });
    uhidInput.addEventListener('focus', function () { uhidWrap.classList.add('is-focus'); });
    uhidInput.addEventListener('blur', function () { uhidWrap.classList.remove('is-focus'); });
    uhidWrap.addEventListener('click', function () { uhidInput.focus(); });
    uhidInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.keyCode === 13) {
        event.preventDefault();
        submitWith(uhidForm, 'action', 'continue');
      }
    });

    var keypad = $('keypad');
    if (keypad) {
      each(keypad.querySelectorAll('button[name="key"]'), function (key) {
        key.addEventListener('click', function (event) {
          event.preventDefault();
          var digits = digitsOf(uhidInput.value);
          if (key.value === 'back') digits = digits.slice(0, -1);
          else if (key.value === 'clear') digits = '';
          else digits = (digits + key.value).slice(0, maxDigits);
          uhidInput.value = digits;
          hideError();
          paint();
        });
      });
    }
    paint();
    if (document.activeElement === uhidInput) uhidWrap.classList.add('is-focus');
  }

  /* ── Keyboard-mode QR scanners on the start screen ───────────── */
  // A USB/Bluetooth scanner "types" the code within a few milliseconds and
  // ends with Enter (or Tab). People pressing keys are much slower, and a TV
  // remote's OK button sends Enter with nothing buffered, so it is ignored.
  var captureForm = $('scanCaptureForm');
  if (captureForm) {
    var buffer = '';
    var lastKeyAt = 0;
    document.addEventListener('keydown', function (event) {
      var target = event.target;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
      var now = Date.now();
      if (now - lastKeyAt > 80) buffer = '';
      lastKeyAt = now;
      var key = event.key;
      if (key === 'Enter' || key === 'Tab') {
        if (digitsOf(buffer).length >= 6) {
          event.preventDefault();
          captureForm.elements.code.value = buffer;
          if (claim(captureForm)) captureForm.submit();
        }
        buffer = '';
      } else if (key && key.length === 1) {
        buffer += key;
      }
    });
  }

  /* ── Scan screen ─────────────────────────────────────────────── */
  var scanForm = $('scanForm');
  if (scanForm) {
    var codeInput = $('scanCode');
    var uhidLength = parseInt(scanForm.getAttribute('data-uhid-length'), 10) || 11;

    // Keep the hidden field focused so a keyboard-mode scanner's keystrokes
    // land in it, unless the patient is on one of the buttons.
    document.addEventListener('click', function (event) {
      var target = event.target;
      while (target && target !== document.body) {
        if (target.tagName === 'A' || target.tagName === 'BUTTON') return;
        target = target.parentNode;
      }
      codeInput.focus();
    });

    if (scanForm.getAttribute('data-camera') === '1') startCamera();
  }

  function startCamera() {
    var video = $('camVideo');
    var callout = $('camCallout');
    var stream = null;
    var timer = null;
    var busy = false;
    var detector = null;

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      if (stream) {
        each(stream.getTracks(), function (track) { track.stop(); });
        stream = null;
      }
      if (video) video.srcObject = null;
    }

    function fail() {
      stop();
      if (callout) callout.hidden = false;
    }

    function found(raw) {
      if (digitsOf(raw).length !== uhidLength) return false;
      stop();
      codeInput.value = raw;
      if (claim(scanForm)) scanForm.submit();
      return true;
    }

    function detect() {
      if (busy || !video || video.readyState < 2) return;
      busy = true;
      detector.detect(video).then(function (codes) {
        busy = false;
        for (var i = 0; i < codes.length; i++) {
          if (found(codes[i].rawValue)) return;
        }
      }).catch(function () { busy = false; });
    }

    try {
      detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    } catch (e) {
      detector = null;
    }
    if (!detector || !video || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      fail();
      return;
    }

    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        var playing = video.play();
        if (playing && playing.catch) playing.catch(function () {});
        timer = setInterval(detect, 350);
      })
      .catch(fail);

    window.addEventListener('pagehide', stop);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop();
    });
  }

  /* ── Idle reset ──────────────────────────────────────────────── */
  var idleSeconds = parseInt(body.getAttribute('data-idle-timeout'), 10) || 0;
  if (idleSeconds > 0) {
    var resetUrl = body.getAttribute('data-reset-url');
    var overlay = $('idleOverlay');
    var overlayText = $('idleBody');
    var template = overlayText ? overlayText.getAttribute('data-template') : '';
    var warnSeconds = Math.min(15, Math.floor(idleSeconds / 3));
    var lastActivity = Date.now();
    var leaving = false;

    var activity = function () {
      lastActivity = Date.now();
      if (overlay && !overlay.hidden) overlay.hidden = true;
    };
    each(['pointerdown', 'touchstart', 'mousedown', 'keydown', 'input', 'wheel', 'scroll'], function (name) {
      document.addEventListener(name, activity, true);
    });

    setInterval(function () {
      if (leaving) return;
      var left = Math.ceil(idleSeconds - (Date.now() - lastActivity) / 1000);
      if (left <= 0) {
        leaving = true;
        window.location.replace(resetUrl);
      } else if (left <= warnSeconds && overlay) {
        overlayText.textContent = template.replace('{n}', left);
        overlay.hidden = false;
      }
    }, 500);
  }
})();
